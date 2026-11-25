"""Vector PDF -> DXF (pypdfium2 checks the file, pdfplumber reads the vector paths and text).

A PDF has no layers, so strokes are grouped by colour and width into layers named `PDF-<RRGGBB>-W<width x100>`
(fills with no stroke: `PDF-FILL-<RRGGBB>`; text: `PDF-TEXT`); the normal layer-mapping step maps them to roles.
The DXF written is in millimetres, at the scale the USER confirmed (this module never decides one), so the
rest of the pipeline is the DXF pipeline. Nothing is dropped silently: images, approximated curves and
rotated pages are returned as issues.
"""

import re
from collections import Counter
from pathlib import Path

import ezdxf
import pdfplumber
import pypdfium2 as pdfium

from api.engine.adapters.dxf.reader import InputError
from api.engine.canonical.model import Issue

MM_PER_PT_AT_1 = 25.4 / 72  # one PDF point on paper, in mm
MAX_PAGES = 50
MAX_OBJECTS = 50_000  # vector objects per page: a backstop like the DXF entity limit, converted before reading


def is_pdf(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(1024).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"%PDF-")


def _colour(c) -> str:
    """RRGGBB of a pdfplumber colour (gray, rgb or cmyk tuple; None = black)."""
    if not c:
        return "000000"
    c = tuple(c) if isinstance(c, (tuple, list)) else (c,)
    if len(c) == 1:
        r = g = b = c[0]
    elif len(c) == 3:
        r, g, b = c
    elif len(c) == 4:
        k = 1 - c[3]
        r, g, b = ((1 - c[i]) * k for i in range(3))
    else:
        return "000000"
    return "".join(f"{round(max(0.0, min(1.0, v)) * 255):02X}" for v in (r, g, b))


def _layer(o: dict) -> str:
    if o.get("stroke", True):
        return f"PDF-{_colour(o.get('stroking_color'))}-W{round((o.get('linewidth') or 0) * 100):d}"
    return f"PDF-FILL-{_colour(o.get('non_stroking_color'))}"


def _open(path: Path):
    try:
        doc = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        raise InputError(f"not a readable PDF (corrupt, or password protected): {e}") from e
    if len(doc) == 0:
        raise InputError("the PDF has no pages")
    if len(doc) > MAX_PAGES:
        raise InputError(f"the PDF has {len(doc)} pages, limit {MAX_PAGES}")
    return doc


def _objects(page) -> list[dict]:
    return [*page.lines, *page.rects, *page.curves]


def _segments(page) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Straight segments in PDF points, y up, for the scale heuristic."""
    h = float(page.height)
    return [((o["pts"][i][0], h - o["pts"][i][1]), (o["pts"][i + 1][0], h - o["pts"][i + 1][1]))
            for o in _objects(page) for i in range(len(o["pts"]) - 1)]


def text_lines(page) -> list[dict]:
    """{text, x, y (baseline-ish, y up), size}."""
    h = float(page.height)
    out = []
    for ln in page.extract_text_lines(return_chars=True):
        text = ln["text"].strip()
        if text:
            out.append({"text": text, "x": float(ln["x0"]), "y": h - float(ln["bottom"]),
                        "size": float(ln["chars"][0].get("size", ln["bottom"] - ln["top"]))})
    return out


def inspect_pdf(path: Path) -> dict:
    """Per page: size, vector object count, images, colour/width groups and scale candidates (never applied)."""
    from api.engine.adapters.pdf.scale import detect_scale_candidates

    doc = _open(path)
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            objs = _objects(page)
            groups = Counter(_layer(o) for o in objs)
            texts = text_lines(page)
            pages.append({
                "number": n, "width_pt": float(page.width), "height_pt": float(page.height),
                "rotation": doc[n - 1].get_rotation(), "vector_objects": len(objs), "images": len(page.images),
                "text_lines": len(texts), "raster_only": not objs and bool(page.images),
                "groups": [{"layer": k, "objects": v} for k, v in sorted(groups.items())],
                "scale_candidates": [c.to_dict() for c in detect_scale_candidates(texts, _segments(page))],
            })
    return {"kind": "pdf", "pages": pages}


def convert_pdf(src: Path, dst: Path, page_number: int, mm_per_pt: float) -> list[Issue]:
    """Write page `page_number` as a millimetre DXF at `mm_per_pt` (paper point -> real mm) to `dst`."""
    if not (mm_per_pt > 0 and mm_per_pt < float("inf")):
        raise InputError("the scale must be a positive number")
    pdoc = _open(src)
    issues: list[Issue] = []
    with pdfplumber.open(str(src)) as pdf:
        if not 1 <= page_number <= len(pdf.pages):
            raise InputError(f"the PDF has {len(pdf.pages)} pages; page {page_number} does not exist")
        page = pdf.pages[page_number - 1]
        h = float(page.height)
        objs = _objects(page)
        if not objs:
            raise InputError(
                "this page has no vector drawing" + (" (it is a scanned image)" if page.images else "")
                + ". Raster scans need the trace-assist feature (coming soon); a PDF exported from CAD works now.")
        if len(objs) > MAX_OBJECTS:
            raise InputError(f"the page has {len(objs)} vector objects, limit {MAX_OBJECTS}")
        doc = ezdxf.new("R2018", setup=False)
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()
        xy = lambda p: (p[0] * mm_per_pt, (h - p[1]) * mm_per_pt)
        curves = 0
        for o in objs:
            layer = _layer(o)
            if layer not in doc.layers:
                doc.layers.add(layer)
            pts = [xy(p) for p in o["pts"]]
            if any(op[0] == "c" for op in o.get("path", ())):
                curves += 1  # the Bezier is kept as the polyline through its anchor points
            closed = len(pts) > 2 and pts[0] == pts[-1]
            if len(pts) == 2:
                msp.add_line(pts[0], pts[1], dxfattribs={"layer": layer})
            elif len(pts) > 2:
                msp.add_lwpolyline(pts[:-1] if closed else pts, close=closed, dxfattribs={"layer": layer})
        if curves:
            issues.append(Issue(code="pdf_curve_approximated", severity="warning",
                                message=f"{curves} curved path(s) were read as straight segments between their anchor points"))
        if page.images:
            issues.append(Issue(code="pdf_images_ignored", severity="warning",
                                message=f"{len(page.images)} image(s) on this page are not reconstructed (raster content)"))
        if rot := pdoc[page_number - 1].get_rotation():
            issues.append(Issue(code="pdf_page_rotated", severity="warning",
                                message=f"the page is rotated {rot} degrees; coordinates are used as drawn, unrotated"))
        doc.layers.add("PDF-TEXT")
        for t in text_lines(page):
            if re.search(r"\S", t["text"]):
                msp.add_text(t["text"], height=max(t["size"] * mm_per_pt, 1.0),
                             dxfattribs={"layer": "PDF-TEXT", "insert": (t["x"] * mm_per_pt, t["y"] * mm_per_pt)})
    doc.saveas(dst)
    return issues
