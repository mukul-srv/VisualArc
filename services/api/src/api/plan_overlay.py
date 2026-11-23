"""Plan overlay: the source drawing's linework next to what the engine built from it, for one project floor.

Read-only (viewer role, like the other project reads). Both sides are in the floor's plan coordinates (mm,
the floor's own scope offset applied), so they line up. The source side is a bounded set of segments (wall
layers first); when it is cut, the response says so (`source.truncated`), never silently.
"""

import itertools
import json

import ezdxf
from fastapi import HTTPException

from api.access import owned
from api.db import GenerationRow, ProjectConventionsRow, ProjectRow, session
from api.engine.adapters.dxf.reader import InputError, load_doc, resolve_scale
from api.engine.conventions import resolve
from api.engine.settings import DEFAULTS
from api.projects import _floor, public_router
from api.sharing import Principal
from api.storage import blob_path, upload_path


def _segments(doc, handles: set[str] | None, k: float, off: tuple[float, float], settings) -> list[tuple]:
    """(layer, x0, y0, x1, y1) in plan mm for LINEs and the edges of LWPOLYLINEs on the floor's entities."""
    out = []
    ox, oy = off
    for e in doc.modelspace():
        if handles is not None and e.dxf.handle not in handles:
            continue
        t, layer = e.dxftype(), e.dxf.layer
        if t == "LINE":
            out.append((layer, e.dxf.start.x * k - ox, e.dxf.start.y * k - oy, e.dxf.end.x * k - ox, e.dxf.end.y * k - oy))
        elif t == "LWPOLYLINE":
            pts = [(p.x * k - ox, p.y * k - oy) for p in e.vertices_in_wcs()]
            ring = pts + pts[:1] if e.closed else pts
            out += [(layer, a[0], a[1], b[0], b[1]) for a, b in itertools.pairwise(ring)]
    return out


@public_router.get("/projects/{pid}/floors/{floor_id}/plan")
def get_plan_overlay(pid: str, floor_id: str, who: Principal):
    with session() as db:
        row = owned(db, ProjectRow, pid, who, "unknown project", need="viewer")
        f = _floor(row, floor_id)
        g = db.get(GenerationRow, f["generation_id"])
        saved = db.get(ProjectConventionsRow, pid)
        if g is None or "request" not in f:
            raise HTTPException(409, "this floor has no stored source drawing (made before requests were kept)")
        prefix = g.blob_prefix
    req = f["request"]
    conv = req.get("conventions") or ({"preset": saved.preset, "mapping": saved.mapping} if saved else None)
    settings = DEFAULTS if conv is None else resolve(conv["preset"], conv["mapping"])
    path = upload_path(req["upload_id"])
    try:
        doc = load_doc(path)
        k = resolve_scale(doc, req.get("units"), bool(req.get("units_override")))
    except (InputError, ezdxf.DXFError) as e:
        raise HTTPException(409, "the source drawing of this floor is missing or unreadable") from e
    if k is None:
        raise HTTPException(409, "the source drawing's units could not be resolved")
    sc = f.get("scope")
    segs = _segments(doc, None if sc is None else set(sc["handles"]), k, (0.0, 0.0) if sc is None else tuple(sc["offset"]), settings)
    # wall layers first, so a cut keeps the walls; then the rest in drawing order
    walls = settings.wall_layers
    segs.sort(key=lambda s: s[0].upper() not in walls)
    cap = settings.plan_overlay_max_segments
    try:
        canon = json.loads(blob_path(f"{prefix}/model.canonical.json").read_text("utf-8"))
        fl = canon["buildings"][0]["floors"][0]
    except (OSError, ValueError, KeyError, IndexError) as e:
        raise HTTPException(409, "this floor's model data is missing or unreadable") from e
    return {
        "floor_id": floor_id,
        "unit": "mm",
        "source": {
            "segments": [{"layer": s[0], "wall": s[0].upper() in walls, "p": [s[1], s[2], s[3], s[4]]} for s in segs[:cap]],
            "total": len(segs),
            "truncated": len(segs) > cap,
        },
        "model": {
            "walls": [{"id": w["id"], "start": w["centreline"]["start"], "end": w["centreline"]["end"], "thickness": w["thickness"]["value"]} for w in fl["walls"]],
            "junctions": [j["polygon"] for j in fl["junctions"]],
            "openings": [{"id": o["id"], "kind": o["kind"], "start": o["span"]["start"], "end": o["span"]["end"], "inferred": o["width"]["source"] == "inferred"} for o in fl["openings"]],
            "boundaries": [{"polygon": b["polygon"], "inferred": b.get("source") == "inferred"} for b in fl["boundaries"]],
        },
    }
