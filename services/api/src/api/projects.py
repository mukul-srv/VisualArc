"""Lightweight projects: an ordered set of floors, each one a generation (B7).

data_dir()/projects/<pid>/project.json. `create_project` and `add_floor` are plain
Python so other code (B8 floor split) can build projects without HTTP.
"""

import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.engine.canonical.model import Measured
from api.generations import GenerationRequest, blocked_response, result, run_generation
from api.storage import data_dir, new_id, valid_id

router = APIRouter(prefix="/api/v1")


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class FloorRequest(GenerationRequest):
    floor_name: str = Field(min_length=1, max_length=100)
    elevation: float = Field(allow_inf_nan=False, description="mm")


def _path(pid: str):
    if not valid_id(pid):
        raise HTTPException(404, "unknown project")
    return data_dir() / "projects" / pid / "project.json"


def load_project(pid: str) -> dict:
    p = _path(pid)
    if not p.is_file():
        raise HTTPException(404, "unknown project")
    return json.loads(p.read_text("utf-8"))


def _save(pid: str, manifest: dict) -> None:
    p = _path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    os.replace(tmp, p)  # a reader never sees a half-written manifest


def create_project(name: str) -> str:
    pid = new_id()
    _save(pid, {"id": pid, "name": name.strip(), "floors": []})
    return pid


def add_floor(pid: str, req: FloorRequest):
    """Generate and append a floor. HTTPException 404 (unknown ids) / 422 (duplicate
    name or elevation); returns the 409 response when blocking issues stop it."""
    # shortcut: read-modify-write without a lock; two concurrent adds to one project
    # can lose a floor. Add a file lock or a DB before multi-user use.
    manifest = load_project(pid)
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
    gid, issues = run_generation(req, floor_id=fid, floor_name=name, floor_elevation=req.elevation)
    if gid is None:
        return blocked_response(issues)
    floor = {
        "id": fid,
        "name": name,
        "elevation": Measured(value=req.elevation, source="user_provided").model_dump(mode="json"),
        "generation_id": gid,
    }
    manifest["floors"].append(floor)
    _save(pid, manifest)
    return {"floor": floor, **result(gid, issues)}


@router.post("/projects", status_code=201)
def post_project(req: ProjectRequest):
    return {"project_id": create_project(req.name)}


@router.post("/projects/{pid}/floors", status_code=201)
def post_floor(pid: str, req: FloorRequest):
    return add_floor(pid, req)


@router.get("/projects/{pid}")
def get_project(pid: str):
    return load_project(pid)
