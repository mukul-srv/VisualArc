"""POST /api/v1/uploads: store a DXF (a DWG is converted first) and run inventory + interpretation (T15).

The body is the raw DXF (Content-Type application/octet-stream), not
multipart: that keeps the dependency set unchanged. The filename is never
used; the file is stored under a server-generated id.
"""


import shutil
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.access import owned
from api.auth import CurrentUser, current_user
from api.db import UploadRow, session
from api.engine.adapters.dwg.convert import convert_in_place, is_dwg
from api.engine.adapters.dxf.inspect import build_inventory
from api.engine.adapters.dxf.reader import InputError, load_doc, read_dxf, resolve_scale
from api.engine.adapters.dxf.split import FloorScope, detect_floors, excluded_issue
from api.engine.adapters.ifc.reader import is_ifc, read_ifc, storeys
from api.engine.adapters.pdf.reader import convert_pdf, inspect_pdf, is_pdf
from api.engine.adapters.pdf.scale import MM_PER_PT_AT_1, ratio_from_two_points
from api.engine.settings import DEFAULTS
from api.generations import GenerationRequest, read_project, request_settings
from api.layer_conventions import preflight, save_conventions
from api.pipeline import has_blocking
from api.projects import FloorRequest, add_floor, create_project, record_version
from api.storage import new_id, upload_key, upload_path

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])



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


async def _ifc_upload(path, upload_id: str, user, filename: str | None) -> dict:
    """An IFC body: read once for the issues and the storeys; the project is made by POST /uploads/{id}/ifc."""
    project = read_ifc(path)
    with session() as db:
        name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255] or None
        db.add(UploadRow(id=upload_id, blob_key=upload_key(upload_id), owner_id=user.id, filename=name))
        db.commit()
    floors = [] if has_blocking(project) else storeys(path)
    return {"upload_id": upload_id, "kind": "ifc", "storeys": floors,
            "inventory": {"layers": [], "entity_counts": {}},  # DXF-only parts of the contract: empty
            "issues": [i.model_dump(mode="json") for i in project.issues], "needs": [],
            "floor_candidates": []}


async def _pdf_upload(path, upload_id: str, user, filename: str | None) -> dict:
    """A PDF body: describe its pages (vector groups, scale suggestions); POST /uploads/{id}/pdf converts it."""
    info = await run_in_threadpool(inspect_pdf, path)
    if all(p["raster_only"] for p in info["pages"]):
        raise InputError("this PDF is a scanned image with no vector drawing. A scan can be traced by hand "
                         "instead (trace-assist: on the project Floors tab, Trace a floor from an image); a PDF exported from CAD converts directly.")
    with session() as db:
        name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255] or None
        db.add(UploadRow(id=upload_id, blob_key=upload_key(upload_id), owner_id=user.id, filename=name))
        db.commit()
    return {"upload_id": upload_id, **info, "inventory": {"layers": [], "entity_counts": {}}, "issues": [],
            "needs": ["scale"], "floor_candidates": []}


@router.post("/uploads", status_code=201)
async def create_upload(request: Request, user: CurrentUser, filename: str | None = None) -> dict:
    upload_id = new_id()
    path = request.state.path = upload_path(upload_id)
    try:
        if not await _save(request, DEFAULTS.max_dxf_bytes):
            raise HTTPException(422, "empty upload: send the file as the request body")
        if is_pdf(path):  # the scale is the user's to confirm: nothing is converted yet
            return await _pdf_upload(path, upload_id, user, filename)
        if is_dwg(path):  # converted to DXF in place; everything after is the DXF pipeline
            await run_in_threadpool(convert_in_place, path)
        if is_ifc(path):
            return await _ifc_upload(path, upload_id, user, filename)
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
            # display only: the base name of what the client says it uploaded, never used as a path
            name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255] or None
            db.add(UploadRow(id=upload_id, blob_key=upload_key(upload_id), owner_id=user.id,
                             filename=name))
            db.commit()
    except BaseException:
        path.unlink(missing_ok=True)  # no blob without its metadata row
        raise
    return {"upload_id": upload_id, "inventory": inventory, **preflight(path, project, DEFAULTS)}


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


def split_plan(upload_id: str, req: GenerationRequest, rows: list[FloorConfirm], user_id: str):
    """Validate the floor rows against the upload's candidates. Returns (jobs, notes, elev) where
    jobs = [(key, FloorRequest, FloorScope, assumed)]; shared by the split and the draft review."""
    with session() as db:
        owned(db, UploadRow, upload_id, user_id, "unknown upload_id")
    path = upload_path(upload_id)
    if not path.is_file():
        raise HTTPException(404, "unknown upload_id")
    try:
        doc = load_doc(path)
    except InputError as e:
        raise HTTPException(422, str(e).replace(str(path), "the uploaded file")) from e
    settings = request_settings(req)
    k = resolve_scale(doc, req.units, req.units_override)
    if k is None:
        raise HTTPException(422, "units missing, conflicting or unsupported; supply units")
    split = detect_floors(doc, k, settings)
    cands = {c.key: c for c in split.candidates}
    if len(cands) < 2:
        raise HTTPException(422, "this upload has no floor split to confirm")
    keys = [f.key for f in rows]
    if sorted(keys) != sorted(cands):  # every candidate confirmed or excluded, once
        raise HTTPException(
            422, f"confirm or exclude exactly the candidates {sorted(cands)}; got {sorted(keys)}"
        )
    kept = [f for f in rows if not f.exclude]
    if not kept:
        raise HTTPException(422, "at least one floor must be built")
    if len({f.name.strip().casefold() for f in kept}) < len(kept):
        raise HTTPException(422, "floor names must be unique")
    # empty elevation: position among the built floors in request order x floor-to-floor, tagged
    step = DEFAULTS.preset(req.building_type).floor_to_floor
    elev, assumed = {}, {}
    for n, f in enumerate(kept):
        if f.elevation is None:
            elev[f.key] = n * step
            assumed[f.key] = (
                f"Floor elevation assumed {n * step:g} mm (floor {n + 1} in floor order "
                f"x {step:g} mm {req.building_type} floor-to-floor)"
            )
        else:
            elev[f.key] = f.elevation
    if len(set(elev.values())) < len(kept):
        raise HTTPException(422, "floor elevations must be unique")
    notes = (*split.issues, *(excluded_issue(cands[f.key]) for f in rows if f.exclude))
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
    return jobs, notes, elev


@router.post("/uploads/{upload_id}/split", status_code=201)
def split_upload(upload_id: str, req: SplitRequest, user: CurrentUser):
    """Confirm the floors of a consolidated DXF: one project, one generation per floor."""
    jobs, notes, elev = split_plan(upload_id, req, req.floors, user.id)
    # Read every floor first so a blocking floor leaves nothing behind. shortcut: each
    # floor is read twice (check, then generate); share the Project if it gets slow.
    blocked = {}
    for n, (key, freq, scope, why) in enumerate(jobs):
        p = read_project(freq, user.id, floor_id=f"floor-{n}", floor_name=freq.floor_name.strip(),
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
    floors = []
    # one transaction: project, floors, generation rows and its single version commit together
    with session() as db, db.begin():
        pid = create_project(req.project_name, user.id, version=False, db=db)
        if req.conventions is not None:
            save_conventions(db, pid, req.conventions)
        for key, freq, scope, why in jobs:
            out = add_floor(pid, freq, scope, user.id, why, version=False, db=db,
                            roof=elev[key] == max(elev.values()))
            if isinstance(out, JSONResponse):  # cannot happen after the check above
                raise HTTPException(500, "floor blocked after the pre-check")
            floors.append({"key": key, **out})
        record_version(db, pid, user.id, f"Created from floor split ({len(floors)} floors)")
    return {
        "project_id": pid,
        "floors": floors,
        "issues": [i.model_dump(mode="json") for i in notes],
    }


class IfcImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_name: str = Field(min_length=1, max_length=100)


@router.post("/uploads/{upload_id}/ifc", status_code=201)
def import_ifc(upload_id: str, req: IfcImport, user: CurrentUser):
    """An uploaded IFC as one project, one floor per storey (name, elevation and every value from the file)."""
    with session() as db:
        owned(db, UploadRow, upload_id, user.id, "unknown upload_id")
    path = upload_path(upload_id)
    if not path.is_file() or not is_ifc(path):
        raise HTTPException(422, "this upload is not an IFC file")
    whole = read_ifc(path)
    issues = [i.model_dump(mode="json") for i in whole.issues]
    if has_blocking(whole):
        return JSONResponse(status_code=409, content={"detail": "blocking issues; no project generated",
                                                      "issues": issues})
    levels = storeys(path)
    elevs = [s["elevation"] for s in levels if s["elevation"] is not None]
    if len(set(elevs)) < len(elevs):
        raise HTTPException(422, "two storeys share an elevation; floors need unique elevations")
    floors, used = [], set()
    with session() as db, db.begin():
        pid = create_project(req.project_name, user.id, version=False, db=db)
        for s in levels:
            name, n = s["name"][:100], 2
            while name.casefold() in used:  # floor names are unique within a project
                name = f"{s['name'][:92]} ({n})"
                n += 1
            used.add(name.casefold())
            freq = FloorRequest(upload_id=upload_id, floor_name=name, elevation=s["elevation"])
            out = add_floor(pid, freq, FloorScope(frozenset({s["key"]}), (0.0, 0.0), ()), user.id, None,
                            version=False, db=db, roof=False)
            if isinstance(out, JSONResponse):
                raise HTTPException(409, f"storey {name!r} is blocked")
            floors.append({"key": s["key"], **out})
        record_version(db, pid, user.id, f"Imported from IFC ({len(floors)} storeys)")
    return {"project_id": pid, "floors": floors, "issues": issues}


class ScaleSpec(BaseModel):
    """The scale the user confirmed: a ratio (100 = 1:100) or two points (PDF points) a known real distance apart."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["ratio", "two_points"]
    ratio: float | None = Field(None, gt=0, le=100_000, allow_inf_nan=False)
    p1: tuple[float, float] | None = None
    p2: tuple[float, float] | None = None
    distance_mm: float | None = Field(None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _complete(self) -> "ScaleSpec":
        need = (self.ratio,) if self.kind == "ratio" else (self.p1, self.p2, self.distance_mm)
        if any(v is None for v in need):
            raise ValueError(f"scale kind {self.kind!r} needs " + ("ratio" if self.kind == "ratio" else "p1, p2 and distance_mm"))
        return self


class PdfConvert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(1, ge=1, le=1000)
    scale: ScaleSpec
    confirmed: bool  # the user ticked "this scale is right"; a suggestion alone never converts

    @model_validator(mode="after")
    def _confirmed(self) -> "PdfConvert":
        if not self.confirmed:
            raise ValueError("the scale must be confirmed by the user")
        return self


@router.post("/uploads/{upload_id}/pdf", status_code=201)
def convert_upload_pdf(upload_id: str, req: PdfConvert, user: CurrentUser) -> dict:
    """Turn one page of an uploaded PDF into the upload's DXF at the confirmed scale, then answer like the DXF
    upload (inventory, issues, needs, floors) so the layer-mapping step follows. Can be repeated (other page or scale)."""
    with session() as db:
        owned(db, UploadRow, upload_id, user.id, "unknown upload_id")
    path = upload_path(upload_id)
    src = path.with_name(path.name + ".pdf")  # the original PDF, kept once the upload holds the DXF
    if not path.is_file():
        raise HTTPException(404, "unknown upload_id")
    try:
        if is_pdf(path):
            shutil.copyfile(path, src)
        elif not src.is_file():
            raise HTTPException(422, "this upload is not a PDF")
        s = req.scale
        ratio = s.ratio if s.kind == "ratio" else ratio_from_two_points(s.p1, s.p2, s.distance_mm)
        tmp = path.with_name(path.name + ".tmp")
        notes = convert_pdf(src, tmp, req.page, ratio * MM_PER_PT_AT_1)
        tmp.replace(path)
        inventory = build_inventory(path)
        project = read_dxf(path, building_type="residential")
    except ValueError as e:  # InputError is one; so is a bad two-point scale
        raise HTTPException(422, str(e).replace(str(path), "the uploaded file")) from e
    pre = preflight(path, project, DEFAULTS)
    return {"upload_id": upload_id, "kind": "dxf", "inventory": inventory, "scale_ratio": ratio,
            **pre, "issues": [*(i.model_dump(mode="json") for i in notes), *pre["issues"]]}
