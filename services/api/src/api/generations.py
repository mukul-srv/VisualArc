"""POST /api/v1/generations and artifact retrieval (T16).

Artifacts are served by (generation id, fixed artifact name) only; no client
string is ever joined into a filesystem path beyond a validated hex id and an
allowlisted name.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api.engine.adapters.dxf.reader import USER_UNITS, InputError, read_dxf
from api.pipeline import has_blocking, write_artifacts
from api.storage import data_dir, new_id, upload_path, valid_id

router = APIRouter(prefix="/api/v1")

# artifact name -> (file suffix written by write_artifacts, media type)
ARTIFACTS = {
    "glb": ("glb", "model/gltf-binary"),
    "meta": ("meta.json", "application/json"),
    "canonical": ("canonical.json", "application/json"),
    "report": ("report.md", "text/markdown"),
}
_STEM = "model"


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: str
    wall_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    ceiling_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    units: Literal[tuple(USER_UNITS)] | None = None  # type: ignore[valid-type]
    door_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    window_height: float | None = Field(None, gt=0, allow_inf_nan=False, description="mm")
    window_sill: float | None = Field(None, ge=0, allow_inf_nan=False, description="mm")


def _dir(generation_id: str):
    return data_dir() / "generations" / generation_id


def run_generation(req: GenerationRequest, **floor) -> tuple[str | None, list[dict]]:
    """Shared by /generations and project floors. `floor` = floor_id/floor_name/
    floor_elevation, passed to read_dxf. Returns (generation_id, issues); the id is
    None when blocking issues stopped it (nothing is stored)."""
    if not valid_id(req.upload_id) or not upload_path(req.upload_id).is_file():
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
            **floor,
        )
    except InputError as e:
        raise HTTPException(
            422, str(e).replace(str(upload_path(req.upload_id)), "the uploaded file")
        ) from e
    issues = [i.model_dump(mode="json") for i in project.issues]
    if has_blocking(project):  # nothing is stored: the client fixes inputs and retries
        return None, issues
    gid = new_id()
    write_artifacts(project, _dir(gid), _STEM)
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
def create_generation(req: GenerationRequest):
    gid, issues = run_generation(req)
    return blocked_response(issues) if gid is None else result(gid, issues)


@router.get("/generations/{generation_id}/artifacts/{name}")
def get_artifact(generation_id: str, name: str):
    if not valid_id(generation_id) or name not in ARTIFACTS:
        raise HTTPException(404, "not found")
    suffix, media = ARTIFACTS[name]
    path = _dir(generation_id) / f"{_STEM}.{suffix}"
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=media)
