"""POST /api/v1/uploads: store a DXF and run inventory + interpretation (T15).

The body is the raw DXF (Content-Type application/octet-stream), not
multipart: that keeps the dependency set unchanged. The filename is never
used; the file is stored under a server-generated id.
"""


from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.auth import CurrentUser, current_user
from api.db import UploadRow, session
from api.engine.adapters.dxf.inspect import build_inventory
from api.engine.adapters.dxf.reader import InputError, load_doc, read_dxf, resolve_scale
from api.engine.adapters.dxf.split import FloorScope, detect_floors, excluded_issue
from api.engine.settings import DEFAULTS
from api.generations import GenerationRequest, read_project
from api.pipeline import has_blocking
from api.projects import FloorRequest, add_floor, create_project
from api.storage import new_id, upload_key, upload_path, valid_id

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])

# preflight issues that mean "the user must supply this parameter"
_NEEDS = {"units_missing": "units"}  # heights are never asked: presets fill them, tagged


async def _save(request: Request, limit: int) -> int:
    """Stream the body to disk; reject as soon as it exceeds `limit` bytes."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"file exceeds the {limit / 2**20:g} MB limit")
    size = 0
    path = request.state.path
    with path.open("wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"file exceeds the {limit / 2**20:g} MB limit")
            f.write(chunk)
    return size


@router.get("/presets")
def get_presets() -> dict:
    """Nominal values per building type (mm), so the web never duplicates them."""
    return {k: asdict(v) for k, v in DEFAULTS.building_presets}


@router.post("/uploads", status_code=201)
async def create_upload(request: Request, user: CurrentUser) -> dict:
    upload_id = new_id()
    path = request.state.path = upload_path(upload_id)
    try:
        if not await _save(request, DEFAULTS.max_dxf_bytes):
            raise HTTPException(422, "empty upload: send the DXF as the request body")
        inventory = build_inventory(path)
        project = read_dxf(path, building_type="residential")
    except InputError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(e).replace(str(path), "the uploaded file")) from e
    except BaseException:
        path.unlink(missing_ok=True)  # size limit, client disconnect, bug: no orphan
        raise
    try:
        with session() as db:
            db.add(UploadRow(id=upload_id, blob_key=upload_key(upload_id), owner_id=user.id))
            db.commit()
    except BaseException:
        path.unlink(missing_ok=True)  # no blob without its metadata row
        raise
    codes = {i.code for i in project.issues}
    candidates = []
    if "floor_split_unconfirmed" in codes:  # read_dxf already checked the units
        doc = load_doc(path)
        candidates = [c.to_dict() for c in detect_floors(doc, resolve_scale(doc)).candidates]
    return {
        "upload_id": upload_id,
        "inventory": inventory,
        "issues": [i.model_dump(mode="json") for i in project.issues],
        "needs": sorted(v for k, v in _NEEDS.items() if k in codes),
        "floor_candidates": candidates,
    }


class FloorConfirm(BaseModel):
    """The user's decision for one candidate: build it (all fields) or exclude it."""

    model_config = ConfigDict(extra="forbid")
    key: str
    exclude: bool = False
    name: str | None = Field(None, min_length=1, max_length=100)
    elevation: float | None = Field(None, allow_inf_nan=False, description="mm")  # None: assumed
    offset_x: float | None = Field(None, allow_inf_nan=False, description="mm")
    offset_y: float | None = Field(None, allow_inf_nan=False, description="mm")

    @model_validator(mode="after")
    def _complete(self) -> "FloorConfirm":
        if not self.exclude and None in (self.name, self.offset_x, self.offset_y):
            raise ValueError(f"{self.key}: name, offset_x and offset_y are required")
        return self


class SplitRequest(GenerationRequest):
    upload_id: str = ""  # unused: the path names the upload
    project_name: str = Field(min_length=1, max_length=100)
    floors: list[FloorConfirm]


@router.post("/uploads/{upload_id}/split", status_code=201)
def split_upload(upload_id: str, req: SplitRequest, user: CurrentUser):
    """Confirm the floors of a consolidated DXF: one project, one generation per floor."""
    path = upload_path(upload_id) if valid_id(upload_id) else None
    if not path or not path.is_file():
        raise HTTPException(404, "unknown upload_id")
    try:
        doc = load_doc(path)
    except InputError as e:
        raise HTTPException(422, str(e).replace(str(path), "the uploaded file")) from e
    k = resolve_scale(doc, req.units)
    if k is None:
        raise HTTPException(422, "units missing, conflicting or unsupported; supply units")
    split = detect_floors(doc, k)
    cands = {c.key: c for c in split.candidates}
    if len(cands) < 2:
        raise HTTPException(422, "this upload has no floor split to confirm")
    keys = [f.key for f in req.floors]
    if sorted(keys) != sorted(cands):  # every candidate confirmed or excluded, once
        raise HTTPException(
            422, f"confirm or exclude exactly the candidates {sorted(cands)}; got {sorted(keys)}"
        )
    kept = [f for f in req.floors if not f.exclude]
    if not kept:
        raise HTTPException(422, "at least one floor must be built")
    if len({f.name.strip().casefold() for f in kept}) < len(kept):
        raise HTTPException(422, "floor names must be unique")
    # empty elevation: position in the detected floor order x floor-to-floor, tagged
    step = DEFAULTS.preset(req.building_type).floor_to_floor
    elev, assumed = {}, {}
    for n, f in enumerate(kept):
        if f.elevation is None:
            elev[f.key] = n * step
            assumed[f.key] = (
                f"Floor elevation assumed {n * step:g} mm (floor {n + 1} in detected order "
                f"x {step:g} mm {req.building_type} floor-to-floor)"
            )
        else:
            elev[f.key] = f.elevation
    if len(set(elev.values())) < len(kept):
        raise HTTPException(422, "floor elevations must be unique")
    notes = (*split.issues, *(excluded_issue(cands[f.key]) for f in req.floors if f.exclude))
    params = req.model_dump(exclude={"upload_id", "project_name", "floors"})
    jobs = [
        (
            f.key,
            FloorRequest(upload_id=upload_id, floor_name=f.name, elevation=elev[f.key], **params),
            FloorScope(cands[f.key].handles, (f.offset_x, f.offset_y), notes),
            assumed.get(f.key),
        )
        for f in kept
    ]
    # Read every floor first so a blocking floor leaves nothing behind. shortcut: each
    # floor is read twice (check, then generate); share the Project if it gets slow.
    blocked = {}
    for n, (key, freq, scope, why) in enumerate(jobs):
        p = read_project(freq, floor_id=f"floor-{n}", floor_name=freq.floor_name.strip(),
                         floor_elevation=freq.elevation, elevation_assumed=why, scope=scope)
        if has_blocking(p):
            blocked[key] = [i.model_dump(mode="json") for i in p.issues]
    if blocked:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "blocking issues; no project generated",
                "issues": [i for v in blocked.values() for i in v],
                "floors": blocked,
            },
        )
    pid = create_project(req.project_name, user.id)
    floors = []
    for key, freq, scope, why in jobs:
        out = add_floor(pid, freq, scope, user.id, why)
        if isinstance(out, JSONResponse):  # cannot happen after the check above
            raise HTTPException(500, "floor blocked after the pre-check")
        floors.append({"key": key, **out})
    return {
        "project_id": pid,
        "floors": floors,
        "issues": [i.model_dump(mode="json") for i in notes],
    }
