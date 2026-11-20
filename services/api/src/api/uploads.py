"""POST /api/v1/uploads: store a DXF and run inventory + interpretation (T15).

The body is the raw DXF (Content-Type application/octet-stream), not
multipart: that keeps the dependency set unchanged. The filename is never
used; the file is stored under a server-generated id.
"""

from fastapi import APIRouter, HTTPException, Request

from api.engine.adapters.dxf.inspect import build_inventory
from api.engine.adapters.dxf.reader import InputError, read_dxf
from api.engine.settings import DEFAULTS
from api.storage import new_id, upload_path

router = APIRouter(prefix="/api/v1")

# preflight issues that mean "the user must supply this parameter"
_NEEDS = {"wall_height_missing": "wall_height", "units_missing": "units"}


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


@router.post("/uploads", status_code=201)
async def create_upload(request: Request) -> dict:
    upload_id = new_id()
    path = request.state.path = upload_path(upload_id)
    try:
        if not await _save(request, DEFAULTS.max_dxf_bytes):
            raise HTTPException(422, "empty upload: send the DXF as the request body")
        inventory = build_inventory(path)
        project = read_dxf(path)
    except InputError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(e).replace(str(path), "the uploaded file")) from e
    except BaseException:
        path.unlink(missing_ok=True)  # size limit, client disconnect, bug: no orphan
        raise
    codes = {i.code for i in project.issues}
    return {
        "upload_id": upload_id,
        "inventory": inventory,
        "issues": [i.model_dump(mode="json") for i in project.issues],
        "needs": sorted(v for k, v in _NEEDS.items() if k in codes),
    }
