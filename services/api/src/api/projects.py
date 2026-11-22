"""Projects: an ordered set of floors, each one a generation (B7), with immutable versions.

`projects.data` holds the current manifest ({id, name, floors, params}); every mutation (create,
add floor, restore) also appends a `project_versions` row, so the latest version always equals the
current state. Versions are never edited or deleted; restoring copies an old snapshot into a new
version. Plain Python helpers (`create_project`, `add_floor`) let the floor-split flow build
projects without HTTP.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.access import owned
from api.auth import CurrentUser, current_user
from api.db import ProjectRow, ProjectVersionRow, session
from api.engine.adapters.dxf.split import FloorScope
from api.engine.canonical.model import Measured
from api.engine.settings import DEFAULTS
from api.generations import GenerationRequest, blocked_response, result, run_generation
from api.storage import new_id

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])

# request fields recorded per floor with provenance (None = the preset fills it, `defaulted`)
_PARAMS = ("building_type", "wall_height", "ceiling_height", "door_height", "window_height",
           "window_sill", "units")


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class FloorRequest(GenerationRequest):
    floor_name: str = Field(min_length=1, max_length=100)
    # None: next elevation = highest existing floor + the preset floor-to-floor, tagged `defaulted`
    elevation: float | None = Field(None, allow_inf_nan=False, description="mm")


def _params(req: GenerationRequest) -> dict:
    return {
        k: {"value": getattr(req, k), "source": "user_provided" if k in req.model_fields_set
            and getattr(req, k) is not None else "defaulted"}
        for k in _PARAMS
    }


def _version(db: Session, row: ProjectRow, user_id: str | None, message: str) -> ProjectVersionRow:
    """Append a version holding the row's current manifest. Caller holds the project row lock."""
    floors = row.data["floors"]
    number = (db.scalar(select(func.max(ProjectVersionRow.number)).where(
        ProjectVersionRow.project_id == row.id)) or 0) + 1
    v = ProjectVersionRow(
        id=new_id(), project_id=row.id, number=number, created_by=user_id, message=message,
        snapshot={"floors": floors, "generation_ids": [f["generation_id"] for f in floors],
                  "params": row.data.get("params", {})},
    )
    db.add(v)
    db.flush()
    db.refresh(v)  # loads the server-side created_at
    return v


def _latest(db: Session, pid: str) -> ProjectVersionRow | None:
    return db.scalars(select(ProjectVersionRow).where(ProjectVersionRow.project_id == pid)
                      .order_by(ProjectVersionRow.number.desc()).limit(1)).first()


def create_project(name: str, owner_id: str | None = None, version: bool = True) -> str:
    """`version=False`: the caller (floor split) writes the first version after adding floors."""
    pid = new_id()
    with session() as db:
        row = ProjectRow(id=pid, data={"id": pid, "name": name.strip(), "floors": [], "params": {}},
                         owner_id=owner_id)
        db.add(row)
        if version:
            _version(db, row, owner_id, "Project created")
        db.commit()
    return pid


def record_version(pid: str, user_id: str, message: str) -> None:
    with session() as db, db.begin():
        _version(db, owned(db, ProjectRow, pid, user_id, "unknown project", lock=True), user_id, message)


def add_floor(
    pid: str,
    req: FloorRequest,
    scope: FloorScope | None = None,
    owner_id: str | None = None,
    assumed: str | None = None,  # set by the split flow when it filled the elevation
    version: bool = True,  # False: the split flow records one version for all its floors
):
    """Generate and append a floor (a new version). HTTPException 404 (unknown or foreign ids)
    / 422 (duplicate name or elevation); returns the 409 response when blocking issues stop it."""
    # the row lock serialises adds to one project, so no floor is lost (and floor ids
    # stay unique); generation runs inside it. shortcut: a long generation blocks
    # other adds to the same project, fine at this scale.
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, owner_id or "", "unknown project", lock=True)
        manifest = row.data
        name = req.floor_name.strip()
        if any(f["name"].casefold() == name.casefold() for f in manifest["floors"]):
            raise HTTPException(422, f"floor name {name!r} already exists in this project")
        elevation = req.elevation
        if elevation is None:
            step = DEFAULTS.preset(req.building_type).floor_to_floor
            top = max((f["elevation"]["value"] for f in manifest["floors"]), default=None)
            elevation = 0.0 if top is None else top + step
            assumed = f"Floor elevation assumed {elevation:g} mm " + (
                "(first floor of the project)"
                if top is None
                else f"(highest floor {top:g} mm + {step:g} mm {req.building_type} floor-to-floor)"
            )
        if any(f["elevation"]["value"] == elevation for f in manifest["floors"]):
            raise HTTPException(
                422, f"a floor at elevation {elevation:g} mm already exists in this project"
            )
        # id = creation index: deterministic, stable when the viewer sorts by elevation,
        # unique within a version (a restore may reuse an id for a different generation)
        fid = f"floor-{len(manifest['floors'])}"
        gid, issues = run_generation(
            req, owner_id, floor_id=fid, floor_name=name, floor_elevation=elevation,
            elevation_assumed=assumed, scope=scope,
        )
        if gid is None:
            return blocked_response(issues)
        floor = {
            "id": fid,
            "name": name,
            "elevation": Measured(
                value=elevation, source="defaulted" if assumed else "user_provided"
            ).model_dump(mode="json"),
            "generation_id": gid,
        }
        row.data = {
            **manifest,
            "floors": [*manifest["floors"], floor],
            "params": {**manifest.get("params", {}), fid: _params(req)},
        }
        if version:
            _version(db, row, owner_id, f"Added floor {name}")
    return {"floor": floor, **result(gid, issues)}


def _manifest(row: ProjectRow, v: ProjectVersionRow) -> dict:
    return {
        "id": row.id, "name": row.data["name"], "floors": v.snapshot["floors"],
        "params": v.snapshot.get("params", {}), "version": v.number,
        "updated_at": v.created_at.isoformat(),
    }


def _info(v: ProjectVersionRow) -> dict:
    return {"number": v.number, "created_at": v.created_at.isoformat(), "created_by": v.created_by,
            "message": v.message, "floor_count": len(v.snapshot["floors"])}


def _version_row(db: Session, pid: str, n: int) -> ProjectVersionRow:
    v = db.scalars(select(ProjectVersionRow).where(
        ProjectVersionRow.project_id == pid, ProjectVersionRow.number == n)).first()
    if v is None:
        raise HTTPException(404, "unknown version")
    return v


@router.post("/projects", status_code=201)
def post_project(req: ProjectRequest, user: CurrentUser):
    return {"project_id": create_project(req.name, user.id)}


@router.get("/projects")
def list_projects(user: CurrentUser):
    with session() as db:
        rows = db.scalars(select(ProjectRow).where(
            ProjectRow.owner_id == user.id, ProjectRow.deleted_at.is_(None))).all()
        out = []
        for r in rows:
            v = _latest(db, r.id)
            out.append({
                "id": r.id, "name": r.data["name"], "floor_count": len(r.data["floors"]),
                "version": v.number if v else 0,
                "updated_at": (v.created_at if v else r.created_at).isoformat(),
                "thumbnail": None,
            })
    return sorted(out, key=lambda p: p["updated_at"], reverse=True)


@router.post("/projects/{pid}/floors", status_code=201)
def post_floor(pid: str, req: FloorRequest, user: CurrentUser):
    return add_floor(pid, req, None, user.id)


@router.get("/projects/{pid}")
def get_project(pid: str, user: CurrentUser, version: int | None = None):
    """Current manifest, or the snapshot of `?version=N` (read-only history)."""
    with session() as db:
        row = owned(db, ProjectRow, pid, user.id, "unknown project")
        v = _latest(db, pid) if version is None else _version_row(db, pid, version)
        return _manifest(row, v)


@router.patch("/projects/{pid}")
def rename_project(pid: str, req: ProjectRequest, user: CurrentUser):
    """Names are metadata, not versioned: every version shows the current name."""
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, user.id, "unknown project", lock=True)
        row.data = {**row.data, "name": req.name.strip()}
    return {"id": pid, "name": req.name.strip()}


@router.delete("/projects/{pid}", status_code=204)
def delete_project(pid: str, user: CurrentUser):
    """Soft delete: the row, versions and blobs stay; the project disappears for everyone."""
    with session() as db, db.begin():
        owned(db, ProjectRow, pid, user.id, "unknown project", lock=True).deleted_at = datetime.now(UTC)
    return Response(status_code=204)


@router.get("/projects/{pid}/versions")
def list_versions(pid: str, user: CurrentUser):
    with session() as db:
        owned(db, ProjectRow, pid, user.id, "unknown project")
        vs = db.scalars(select(ProjectVersionRow).where(ProjectVersionRow.project_id == pid)
                        .order_by(ProjectVersionRow.number.desc())).all()
        return [_info(v) for v in vs]


@router.get("/projects/{pid}/versions/{number}")
def get_version(pid: str, number: int, user: CurrentUser):
    with session() as db:
        owned(db, ProjectRow, pid, user.id, "unknown project")
        v = _version_row(db, pid, number)
        return {**_info(v), "snapshot": v.snapshot}


@router.post("/projects/{pid}/versions/{number}/restore", status_code=201)
def restore_version(pid: str, number: int, user: CurrentUser):
    """New version copying an old snapshot; history is never rewritten."""
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, user.id, "unknown project", lock=True)
        old = _version_row(db, pid, number)
        row.data = {**row.data, "floors": old.snapshot["floors"],
                    "params": old.snapshot.get("params", {})}
        return _info(_version(db, row, user.id, f"Restored version {number}"))
