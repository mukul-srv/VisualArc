"""Lightweight projects: an ordered set of floors, each one a generation (B7).

Rows in the `projects` table (manifest in a JSONB column). `create_project` and `add_floor` are plain
Python so other code (B8 floor split) can build projects without HTTP.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.auth import CurrentUser, current_user
from api.db import ProjectRow, session
from api.engine.adapters.dxf.split import FloorScope
from api.engine.canonical.model import Measured
from api.generations import GenerationRequest, blocked_response, result, run_generation
from api.storage import new_id, valid_id

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class FloorRequest(GenerationRequest):
    floor_name: str = Field(min_length=1, max_length=100)
    elevation: float = Field(allow_inf_nan=False, description="mm")


def load_project(pid: str) -> dict:
    if not valid_id(pid):
        raise HTTPException(404, "unknown project")
    with session() as db:
        row = db.get(ProjectRow, pid)
    if row is None:
        raise HTTPException(404, "unknown project")
    return row.data


def create_project(name: str, owner_id: str | None = None) -> str:
    pid = new_id()
    with session() as db:
        db.add(ProjectRow(id=pid, data={"id": pid, "name": name.strip(), "floors": []}, owner_id=owner_id))
        db.commit()
    return pid


def add_floor(
    pid: str, req: FloorRequest, scope: FloorScope | None = None, owner_id: str | None = None
):
    """Generate and append a floor. HTTPException 404 (unknown ids) / 422 (duplicate
    name or elevation); returns the 409 response when blocking issues stop it."""
    if not valid_id(pid):
        raise HTTPException(404, "unknown project")
    # the row lock serialises adds to one project, so no floor is lost (and floor ids
    # stay unique); generation runs inside it. shortcut: a long generation blocks
    # other adds to the same project, fine at this scale.
    with session() as db, db.begin():
        row = db.get(ProjectRow, pid, with_for_update=True)
        if row is None:
            raise HTTPException(404, "unknown project")
        manifest = row.data
        name = req.floor_name.strip()
        if any(f["name"].casefold() == name.casefold() for f in manifest["floors"]):
            raise HTTPException(422, f"floor name {name!r} already exists in this project")
        if any(f["elevation"]["value"] == req.elevation for f in manifest["floors"]):
            raise HTTPException(
                422, f"a floor at elevation {req.elevation:g} mm already exists in this project"
            )
        # id = creation index: deterministic, stable when the viewer sorts by elevation,
        # unique because floors are append-only (never deleted)
        fid = f"floor-{len(manifest['floors'])}"
        gid, issues = run_generation(
            req, owner_id, floor_id=fid, floor_name=name, floor_elevation=req.elevation, scope=scope
        )
        if gid is None:
            return blocked_response(issues)
        floor = {
            "id": fid,
            "name": name,
            "elevation": Measured(value=req.elevation, source="user_provided").model_dump(mode="json"),
            "generation_id": gid,
        }
        row.data = {**manifest, "floors": [*manifest["floors"], floor]}
    return {"floor": floor, **result(gid, issues)}


@router.post("/projects", status_code=201)
def post_project(req: ProjectRequest, user: CurrentUser):
    return {"project_id": create_project(req.name, user.id)}


@router.post("/projects/{pid}/floors", status_code=201)
def post_floor(pid: str, req: FloorRequest, user: CurrentUser):
    return add_floor(pid, req, None, user.id)


@router.get("/projects/{pid}")
def get_project(pid: str):
    return load_project(pid)
