"""POST /api/v1/generations and artifact retrieval (T16).

Artifacts are served by (generation id, fixed artifact name) only; no client
string is ever joined into a filesystem path beyond a validated hex id and an
allowlisted name.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from api.access import owned
from api.auth import CurrentUser, current_user
from api.db import GenerationRow, ProjectRow, ProjectVersionRow, UploadRow, session
from api.engine.adapters.dxf.reader import USER_UNITS, InputError, read_dxf
from api.engine.canonical.model import Project
from api.engine.conventions import resolve
from api.engine.parameters import PARAMS
from api.engine.settings import DEFAULTS
from api.pipeline import has_blocking, write_artifacts
from api.sharing import Principal
from api.storage import blob_path, new_id, upload_path

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])
public_router = APIRouter(prefix="/api/v1")  # readable via a share link too

# artifact name -> (file suffix written by write_artifacts, media type)
ARTIFACTS = {
    "glb": ("glb", "model/gltf-binary"),
    "meta": ("meta.json", "application/json"),
    "canonical": ("canonical.json", "application/json"),
    "report": ("report.md", "text/markdown"),
}
_STEM = "model"


class ConventionsSpec(BaseModel):
    """Layer conventions for one generation: a preset and extra layer -> role entries."""

    model_config = ConfigDict(extra="forbid")
    preset: str = Field("aia", max_length=20)
    mapping: dict[str, str] = Field(default_factory=dict, max_length=200)

    @field_validator("mapping")
    @classmethod
    def _key_length(cls, m: dict[str, str]) -> dict[str, str]:
        if any(len(k) > 255 or len(v) > 20 for k, v in m.items()):  # DXF layer names are <= 255
            raise ValueError("layer names are at most 255 characters and roles at most 20")
        return m

    @model_validator(mode="after")
    def _valid(self) -> "ConventionsSpec":
        try:
            resolve(self.preset, self.mapping)
        except ValueError as e:
            raise ValueError(str(e)) from e
        return self


# parameters with no dedicated reader argument (ceiling_height and window_sill have one)
EXTRA_PARAMS = tuple(k for k in PARAMS if k not in ("ceiling_height", "window_sill", "wall_height"))


class ParamFields(BaseModel):
    """The project parameters (engine/parameters.py). None = the preset's value, tagged `defaulted`."""

    model_config = ConfigDict(extra="forbid")
    wall_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    ceiling_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    window_sill: float | None = Field(None, ge=0, allow_inf_nan=False, description="mm")
    slab_thickness: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    roof_type: Literal["flat", "gable", "hip"] | None = None
    roof_pitch: float | None = Field(None, ge=0, lt=90, allow_inf_nan=False, description="degrees")
    stair_rise: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    stair_run: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    lintel_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    railing_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")


class GenerationRequest(ParamFields):
    upload_id: str
    units: Literal[tuple(USER_UNITS)] | None = None  # type: ignore[valid-type]
    door_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    window_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    # missing heights are filled from this type's preset (tagged `defaulted`, with a warning)
    building_type: Literal["residential", "commercial"] = "residential"
    # None: the project's saved conventions (floors) or the AIA default
    conventions: ConventionsSpec | None = None


def _prefix(generation_id: str) -> str:
    return f"generations/{generation_id}"


def request_settings(req: "GenerationRequest"):
    c = req.conventions
    return DEFAULTS if c is None else resolve(c.preset, c.mapping)


def read_project(req: GenerationRequest, user_id: str | None = None, check_upload: bool = True,
                 **floor) -> Project:
    """Read the upload (owned by `user_id`) into a Project; nothing is stored. `floor` =
    floor_id/floor_name/floor_elevation/scope, passed to read_dxf."""
    if check_upload:  # False: the caller already holds project access to a stored request
        with session() as db:
            owned(db, UploadRow, req.upload_id, user_id or "", "unknown upload_id")
    if not upload_path(req.upload_id).is_file():
        raise HTTPException(404, "unknown upload_id")
    try:
        project = read_dxf(
            upload_path(req.upload_id),
            req.wall_height,
            user_units=req.units,
            door_height=req.door_height,
            window_height=req.window_height,
            window_sill=req.window_sill,
            ceiling_height=req.ceiling_height,
            params={k: getattr(req, k) for k in EXTRA_PARAMS if getattr(req, k) is not None},
            building_type=req.building_type,
            settings=request_settings(req),
            **floor,
        )
    except InputError as e:
        raise HTTPException(
            422, str(e).replace(str(upload_path(req.upload_id)), "the uploaded file")
        ) from e
    return project


def run_generation(
    req: GenerationRequest, owner_id: str | None = None, db=None, progress=None,
    check_upload: bool = True, **floor
) -> tuple[str | None, list[dict]]:
    """Shared by /generations and project floors. Returns (generation_id, issues);
    `progress(stage)` reports stages to a job; the id is None when blocking issues stopped it (nothing is stored). With `db` the
    row joins the caller's transaction (the caller commits); blobs are never rolled back."""
    if progress:
        progress("parsing")
    project = read_project(req, owner_id, check_upload, **floor)
    if progress:
        progress("building-model")
    issues = [i.model_dump(mode="json") for i in project.issues]
    if has_blocking(project):  # nothing is stored: the client fixes inputs and retries
        return None, issues
    gid = new_id()
    write_artifacts(project, blob_path(f"{_prefix(gid)}/{_STEM}.glb").parent, _STEM,
                    progress=progress)
    with session() as q:
        up = q.get(UploadRow, req.upload_id)
        name = up.filename[:100] if up and up.filename else None
    row = GenerationRow(id=gid, blob_prefix=_prefix(gid), owner_id=owner_id, name=name)
    if db is not None:
        db.add(row)
    else:
        with session() as own:
            own.add(row)
            own.commit()
    return gid, issues


def blocked_response(issues: list[dict]) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "blocking issues; no model generated", "issues": issues},
    )


def result(gid: str, issues: list[dict]) -> dict:
    return {
        "generation_id": gid,
        "issues": issues,
        "artifacts": {k: f"/api/v1/generations/{gid}/artifacts/{k}" for k in ARTIFACTS},
    }


@router.post("/generations", status_code=201)
def create_generation(req: GenerationRequest, user: CurrentUser):
    gid, issues = run_generation(req, user.id)
    return blocked_response(issues) if gid is None else result(gid, issues)


@router.get("/generations/recent")
def recent_generations(user: CurrentUser):
    """My last 10 generations with their project and floor names (none for standalone ones).
    Generations of deleted projects are hidden."""
    with session() as db:
        where = {}  # generation id -> (project row, floor name)
        for p in db.scalars(select(ProjectRow).where(ProjectRow.owner_id == user.id)):
            for f in p.data["floors"]:
                where[f["generation_id"]] = (p, f)
        # every generation a project of mine ever used (older versions, deleted projects too) is the
        # project's, not a standalone model: it is changed through the project
        used = {gid for (ids,) in db.execute(
            select(ProjectVersionRow.snapshot["generation_ids"]).join(
                ProjectRow, ProjectRow.id == ProjectVersionRow.project_id)
            .where(ProjectRow.owner_id == user.id)) for gid in (ids or [])}
        gens = db.scalars(select(GenerationRow).where(
            GenerationRow.owner_id == user.id, GenerationRow.deleted_at.is_(None))
            .order_by(GenerationRow.created_at.desc())).all()
    out = []
    for g in gens:
        p, floor = where.get(g.id, (None, None))
        if p is None and g.id in used:
            continue
        if p is not None and p.deleted_at is not None:
            continue
        out.append({"generation_id": g.id, "created_at": g.created_at.isoformat(),
                    "name": g.name,
                    "project_id": p and p.id, "project_name": p and p.data["name"],
                    "floor_name": floor and floor["name"], "floor_id": floor and floor["id"],
                    "artifacts": result(g.id, [])["artifacts"]})
        if len(out) == 10:
            break
    return out


class GenerationRename(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)


def _standalone(db, g: GenerationRow) -> None:
    """409 when a project uses the generation: those are changed through the project."""
    used = db.scalar(select(ProjectVersionRow.id).where(
        ProjectVersionRow.snapshot["generation_ids"].contains([g.id])).limit(1))
    if used is not None:
        raise HTTPException(409, "this model belongs to a project; change it there")


@router.patch("/generations/{generation_id}")
def rename_generation(generation_id: str, req: GenerationRename, user: CurrentUser) -> dict:
    """Rename a standalone model (owner). Its default name is the uploaded file name."""
    with session() as db, db.begin():
        g = owned(db, GenerationRow, generation_id, user.id, "unknown generation")
        _standalone(db, g)
        g.name = req.name
    return {"generation_id": generation_id, "name": req.name}


@router.delete("/generations/{generation_id}", status_code=204)
def delete_generation(generation_id: str, user: CurrentUser) -> Response:
    """Soft delete a standalone model (owner): it leaves the lists and its files give 404, the
    stored files stay (same as projects)."""
    with session() as db, db.begin():
        g = owned(db, GenerationRow, generation_id, user.id, "unknown generation")
        _standalone(db, g)
        g.deleted_at = datetime.now(UTC)
    return Response(status_code=204)


@public_router.get("/generations/{generation_id}/artifacts/{name}")
def get_artifact(generation_id: str, name: str, who: Principal):
    if name not in ARTIFACTS:
        raise HTTPException(404, "not found")
    with session() as db:
        owned(db, GenerationRow, generation_id, who, "not found", need="viewer")
    suffix, media = ARTIFACTS[name]
    path = blob_path(f"{_prefix(generation_id)}/{_STEM}.{suffix}")
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=media)
