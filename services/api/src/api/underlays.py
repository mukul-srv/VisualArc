"""Trace-assist underlays (Phase 1/25): a raster image under an empty floor, to trace over by hand.

Nothing is detected or vectorised: the image is only a picture. A floor made from it starts empty (an empty
mm DXF marked `trace-blank`, see `make_blank_dxf`), the user calibrates the scale with two clicks and a real
distance (`user_provided`), and draws walls, doors and windows with the normal plan editor. The image is
checked by content (never by name or declared type), pixel- and byte-capped, re-encoded as PNG (metadata
dropped) and stored as a blob; the manifest floor keeps `underlay = {blob, width_px, height_px, calibration}`.
Pixel (px, py) (origin top-left, y down) is plan (px * m, (height_px - py) * m), m = mm per pixel.
"""

import io
import math
from typing import Annotated

import pypdfium2 as pdfium
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from api.access import owned
from api.auth import CurrentUser
from api.db import ProjectRow, UploadRow, session
from api.engine.adapters.dxf.reader import make_blank_dxf
from api.engine.settings import DEFAULTS
from api.projects import (
    FloorRequest,
    _floor,
    _version,
    add_floor,
    create_project,
    public_router,
    router,
)
from api.sharing import Principal
from api.storage import blob_path, new_id, put_blob, upload_key, upload_path

MIN_CALIBRATION_PX = 10.0  # two points closer than this give a scale that is mostly click noise


def calibration(p1, p2, distance_mm: float) -> dict:
    """The user's two-point calibration as stored: mm per image pixel, `user_provided`."""
    px = math.dist(p1, p2)
    if px < MIN_CALIBRATION_PX:
        raise ValueError(f"the two points are {px:.1f} px apart; pick points at least {MIN_CALIBRATION_PX:g} px apart")
    if not (distance_mm > 0 and math.isfinite(distance_mm)):
        raise ValueError("the real distance must be a positive number of mm")
    return {"p1": list(p1), "p2": list(p2), "distance_mm": distance_mm, "mm_per_px": distance_mm / px,
            "source": "user_provided"}


def normalize(data: bytes) -> tuple[bytes, int, int]:
    """(PNG bytes, width, height) of a PNG/JPEG image or page 1 of a PDF, judged by content. ValueError = rejected."""
    s = DEFAULTS
    if len(data) > s.underlay_max_bytes:
        raise ValueError(f"the file is {len(data) / 2**20:.1f} MB, limit {s.underlay_max_bytes / 2**20:g} MB")
    if data.lstrip()[:5] == b"%PDF-":
        im = _render_pdf(data)
    else:
        Image.MAX_IMAGE_PIXELS = s.underlay_max_pixels  # Pillow's own decompression-bomb guard (errors at 2x)
        try:
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format not in ("PNG", "JPEG"):
                    raise ValueError("only PNG, JPEG and PDF files can be used as an underlay")
                if probe.width * probe.height > s.underlay_max_pixels:
                    raise ValueError(f"the image has {probe.width * probe.height / 1e6:.0f} megapixels, "
                                     f"limit {s.underlay_max_pixels / 1e6:g}")
                im = probe.convert("RGB")  # decodes; alpha and metadata are dropped
        except Image.DecompressionBombError as e:
            raise ValueError("the image has far too many pixels (decompression-bomb guard)") from e
        except (UnidentifiedImageError, OSError) as e:
            raise ValueError("this file is not a readable PNG, JPEG or PDF image") from e
    if max(im.size) > s.underlay_max_side_px:
        im.thumbnail((s.underlay_max_side_px, s.underlay_max_side_px))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue(), im.width, im.height


def _render_pdf(data: bytes) -> Image.Image:
    """Page 1 of a PDF as a picture (a scan, or any drawing used as a backdrop)."""
    s = DEFAULTS
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise ValueError("this PDF could not be opened (corrupt or password protected)") from e
    try:
        if len(doc) == 0:
            raise ValueError("the PDF has no pages")
        page = doc[0]
        w, h = page.get_size()
        scale = min(s.underlay_pdf_dpi / 72, s.underlay_max_side_px / max(w, h))
        if w * scale * h * scale > s.underlay_max_pixels:
            raise ValueError("the PDF page is too large to render")
        return page.render(scale=scale).to_pil().convert("RGB")
    finally:
        doc.close()


async def _body(request: Request, limit: int) -> bytes:
    """The request body, rejected as soon as it exceeds `limit` bytes."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"file exceeds the {limit / 2**20:g} MB limit")
    chunks, size = [], 0
    async for c in request.stream():
        size += len(c)
        if size > limit:
            raise HTTPException(413, f"file exceeds the {limit / 2**20:g} MB limit")
        chunks.append(c)
    if not size:
        raise HTTPException(422, "empty upload: send the image as the request body")
    return b"".join(chunks)


@router.post("/trace/floors", status_code=201)
async def create_trace_floor(request: Request, user: CurrentUser, floor_name: Annotated[str, Field(min_length=1, max_length=100)],
                             project_id: str | None = None, project_name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
                             elevation: float | None = None, filename: str | None = None):
    """A new empty floor with the image as its underlay: in `project_id` (editor+), or in a new project
    `project_name`. The scale is still uncalibrated: the plan editor asks for it before anything can be traced."""
    if (project_id is None) == (project_name is None):
        raise HTTPException(422, "give either project_id or project_name")
    if elevation is not None and not math.isfinite(elevation):
        raise HTTPException(422, "elevation must be a number")
    raw = await _body(request, DEFAULTS.underlay_max_bytes)
    try:
        png, w, h = await run_in_threadpool(normalize, raw)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    uid, blob = new_id(), new_id()
    src = upload_path(uid)
    make_blank_dxf(src)
    shown = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255] or None
    with session() as first, first.begin():  # committed first: generation checks the upload in its own session
        first.add(UploadRow(id=uid, blob_key=upload_key(uid), owner_id=user.id, filename="traced floor"))
    with session() as db, db.begin():
        pid = project_id or create_project(project_name, user.id, version=False, db=db)
        out = add_floor(pid, FloorRequest(upload_id=uid, floor_name=floor_name, elevation=elevation), None, user.id,
                        None, version=False, db=db, roof=False)
        if not isinstance(out, dict):  # a blank floor cannot block; a project failure is an HTTPException above
            raise HTTPException(500, "the empty floor could not be created")
        row = owned(db, ProjectRow, pid, user.id, "unknown project", lock=True, need="editor")
        fid = out["floor"]["id"]
        put_blob(f"underlays/{blob}.png", png)  # after the checks that can fail; an orphan blob is harmless
        under = {"blob": blob, "width_px": w, "height_px": h, "calibration": None, "name": shown}
        row.data = {**row.data, "floors": [{**f, "underlay": under} if f["id"] == fid else f for f in row.data["floors"]]}
        _version(db, row, user.id, f"Added traced floor {floor_name}")
    return {"project_id": pid, "floor": {**out["floor"], "underlay": under}, "issues": out["issues"]}


def _underlay(row: ProjectRow, floor_id: str) -> dict:
    u = _floor(row, floor_id).get("underlay")
    if u is None:
        raise HTTPException(404, "this floor has no underlay")
    return u


@public_router.get("/projects/{pid}/floors/{floor_id}/underlay")
def get_underlay(pid: str, floor_id: str, who: Principal):
    with session() as db:
        row = owned(db, ProjectRow, pid, who, "unknown project", need="viewer")
        u = _underlay(row, floor_id)
    path = blob_path(f"underlays/{u['blob']}.png")
    if not path.is_file():
        raise HTTPException(404, "the underlay image is missing")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p1: tuple[float, float]  # image pixels, origin top-left
    p2: tuple[float, float]
    distance_mm: float = Field(gt=0, allow_inf_nan=False)


@router.put("/projects/{pid}/floors/{floor_id}/underlay/calibration")
def put_calibration(pid: str, floor_id: str, req: Calibration, user: CurrentUser) -> dict:
    """Store the user's two-point scale (editor+, new version). Traced walls stay as they are (mm); only the
    picture is rescaled."""
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, user.id, "unknown project", lock=True, need="editor")
        u = _underlay(row, floor_id)
        if not all(0 <= x <= u["width_px"] and 0 <= y <= u["height_px"] for x, y in (req.p1, req.p2)):
            raise HTTPException(422, "both points must lie on the image")
        try:
            cal = calibration(req.p1, req.p2, req.distance_mm)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        u = {**u, "calibration": cal}
        row.data = {**row.data, "floors": [{**f, "underlay": u} if f["id"] == floor_id else f for f in row.data["floors"]]}
        _version(db, row, user.id, f"Calibrated underlay of {_floor(row, floor_id)['name']}")
    return u

