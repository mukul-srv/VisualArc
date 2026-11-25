"""Building assembly (Phase 1/13): the project's floors read as one connected building.

Floors stack by their own `elevation` (no building-level height table) and share one plan origin.
Each floor may carry a manual X/Y `offset` (user_provided, pure translation of its plan, stored in
the project manifest; the generated model is never altered, consumers apply it). Stairs are paired
across adjacent floors by footprint overlap; the persisted list (`manifest["pairings"]`) keeps the
user's decisions (`confirmed`, `rejected`); `auto` pairs are recomputed on every read, so they follow
offsets and regenerated floors. Nothing is guessed silently: mismatches become explicit issues.
"""

import itertools
import json
from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Polygon, box

from api.access import owned, project_role
from api.auth import CurrentUser
from api.db import GenerationRow, ProjectRow, session
from api.engine.canonical.model import Floor, Project
from api.projects import NO_LIGHTING, _floor, _latest, _version, public_router, router
from api.sharing import Principal
from api.storage import blob_path

PAIR_MIN_OVERLAP = 0.5  # footprint overlap / smaller footprint for an automatic pair
ALIGN_MIN_CONTAINMENT = 0.75  # bbox overlap / smaller bbox below which adjacent floors are "mismatched"
ALIGN_SAME_SIZE = 0.02  # bboxes this close in size count as the same plan ...
ALIGN_MAX_SHIFT_MM = 300.0  # ... and a shift beyond this is a clear offset
RISE_TOL_MM = 1.0  # stair rise vs floor gap


@dataclass
class FloorData:
    """One floor of the building: manifest entry + what the assembly reads from its canonical model."""

    id: str
    name: str
    elevation: float
    finished: float
    top: float
    generation_id: str
    roof: bool
    offset: tuple[float, float]
    offset_source: str
    bbox: tuple[float, float, float, float] | None  # shifted by the offset
    area: float
    rooms: int
    stairs: list[dict] = field(default_factory=list)  # {id, polygon (shifted), total_rise}
    unreadable: bool = False


def _bbox(f: Floor) -> tuple[float, float, float, float] | None:
    pts = []
    for w in f.walls:
        h = w.thickness.value / 2
        for x, y in (w.centreline.start, w.centreline.end):
            pts += [(x - h, y - h), (x + h, y + h)]
    pts += [p for b in f.boundaries for p in b.polygon]
    if not pts:
        return None
    xs, ys = zip(*pts, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _shift(pt, off):
    return (pt[0] + off[0], pt[1] + off[1])


def _load(db, mf: dict) -> FloorData:
    o = mf.get("offset") or {}
    off = (o.get("x", 0.0), o.get("y", 0.0))
    base = {"id": mf["id"], "name": mf["name"], "elevation": mf["elevation"]["value"],
                "generation_id": mf["generation_id"], "roof": bool(mf.get("roof")), "offset": off,
                "offset_source": o.get("source", "defaulted")}
    g = db.get(GenerationRow, mf["generation_id"])
    try:
        canon = Project.model_validate(json.loads(
            blob_path(f"{g.blob_prefix}/model.canonical.json").read_text("utf-8")))
        f = canon.buildings[0].floors[0]
    except (AttributeError, OSError, ValueError, IndexError):
        return FloorData(**base, finished=base["elevation"], top=base["elevation"], bbox=None,
                         area=0.0, rooms=0, unreadable=True)
    wall_h = max((w.height.value for w in f.walls if w.height), default=0.0)
    bb = _bbox(f)
    return FloorData(
        **base, finished=f.finished_level_mm,
        top=f.finished_level_mm + (f.ceiling_height.value if f.ceiling_height else wall_h),
        bbox=None if bb is None else (bb[0] + off[0], bb[1] + off[1], bb[2] + off[0], bb[3] + off[1]),
        area=sum(r.area.value for r in f.rooms), rooms=len(f.rooms),
        stairs=[{"id": s.id, "polygon": [_shift(p, off) for p in s.polygon],
                 "total_rise": s.total_rise.value if s.total_rise else None} for s in f.stairs])


def _overlap(a: list, b: list) -> float:
    """Shared area / the smaller footprint (0 when invalid or disjoint)."""
    pa, pb = Polygon(a), Polygon(b)
    if not (pa.is_valid and pb.is_valid) or min(pa.area, pb.area) <= 0:
        return 0.0
    return pa.intersection(pb).area / min(pa.area, pb.area)


_FIELDS = ("lower_floor", "lower_stair", "upper_floor", "upper_stair")


def _key(p: dict) -> tuple:
    return (p["lower_floor"], p["lower_stair"], p["upper_floor"], p["upper_stair"])


def effective_pairings(floors: list[FloorData], saved: list[dict]) -> tuple[list[dict], list[dict]]:
    """(pairings, issues). `floors` sorted by elevation. Saved `confirmed` pairs hold their stairs,
    `rejected` pairs are never auto-paired again, `auto` is recomputed: greedy by overlap."""
    by = {f.id: f for f in floors}
    nxt = {a.id: b.id for a, b in itertools.pairwise(floors)}
    out, issues, taken, rejected = [], [], set(), set()
    for p in saved:
        lo, up = by.get(p["lower_floor"]), by.get(p["upper_floor"])
        ls = next((s for s in lo.stairs if s["id"] == p["lower_stair"]), None) if lo else None
        us = next((s for s in up.stairs if s["id"] == p["upper_stair"]), None) if up else None
        if ls is None or us is None or nxt.get(p["lower_floor"]) != p["upper_floor"]:
            if p["status"] != "auto":
                issues.append(_issue(
                    "pairing_stale", "warning", f"a {p['status']} stair pairing "
                    f"({p['lower_stair']} -> {p['upper_stair']}) no longer matches the floors and was dropped",
                    [p["lower_floor"], p["upper_floor"]]))
            continue
        if p["status"] == "rejected":
            rejected.add(_key(p))
        elif p["status"] == "confirmed":
            taken |= {(p["lower_floor"], p["lower_stair"]), (p["upper_floor"], p["upper_stair"])}
        else:
            continue
        out.append({**{k: p[k] for k in (*_FIELDS, "status")}, "overlap": _overlap(ls["polygon"], us["polygon"])})
    for lo in floors[:-1]:
        up = by[nxt[lo.id]]
        cands = sorted(((_overlap(a["polygon"], b["polygon"]), a["id"], b["id"])
                        for a in lo.stairs for b in up.stairs), reverse=True)
        for ov, a, b in cands:
            p = {"lower_floor": lo.id, "lower_stair": a, "upper_floor": up.id, "upper_stair": b}
            if (ov < PAIR_MIN_OVERLAP or _key(p) in rejected
                    or (lo.id, a) in taken or (up.id, b) in taken):
                continue
            taken |= {(lo.id, a), (up.id, b)}
            out.append({**p, "status": "auto", "overlap": ov})
    return out, issues


def _issue(code: str, severity: str, message: str, floors: list[str]) -> dict:
    return {"code": code, "severity": severity, "message": message, "sources": [], "floor_ids": floors}


def _flat(bb) -> bool:
    """No outline, or a zero-area one (a single line): it cannot be compared."""
    return bb is None or bb[2] <= bb[0] or bb[3] <= bb[1]


def check_alignment(floors: list[FloorData]) -> list[dict]:
    """Warn (never shift) when adjacent floors' outlines clearly differ in position."""
    out = []
    for f in floors:
        if f.unreadable:
            out.append(_issue("floor_data_unreadable", "warning",
                              f"floor {f.name!r}: its model data is missing or unreadable", [f.id]))
        elif _flat(f.bbox):
            out.append(_issue("floor_no_outline", "info", f"floor {f.name!r} has no walls or floor "
                              "outline (or only a line), so it cannot be checked for alignment", [f.id]))
    for a, b in itertools.pairwise(floors):
        if _flat(a.bbox) or _flat(b.bbox):
            continue
        ba, bb = box(*a.bbox), box(*b.bbox)
        inter = ba.intersection(bb).area
        contain = inter / min(ba.area, bb.area)
        wa, ha, wb, hb = a.bbox[2] - a.bbox[0], a.bbox[3] - a.bbox[1], b.bbox[2] - b.bbox[0], b.bbox[3] - b.bbox[1]
        shift = (b.bbox[0] - a.bbox[0], b.bbox[1] - a.bbox[1])
        same = abs(wa - wb) <= ALIGN_SAME_SIZE * max(wa, wb) and abs(ha - hb) <= ALIGN_SAME_SIZE * max(ha, hb)
        if contain < ALIGN_MIN_CONTAINMENT:
            msg = (f"outlines of {a.name!r} and {b.name!r} barely overlap ({contain:.0%} of the smaller)"
                   f"; their plans may not share an origin. Set a floor offset if {b.name!r} is shifted")
        elif same and max(abs(shift[0]), abs(shift[1])) > ALIGN_MAX_SHIFT_MM:
            msg = (f"{b.name!r} has the same size as {a.name!r} but sits {shift[0]:g}, {shift[1]:g} mm "
                   f"(x, y) from it; an offset of {-shift[0]:g}, {-shift[1]:g} mm would align it")
        else:
            continue
        out.append(_issue("floor_alignment_mismatch", "warning", msg, [a.id, b.id]))
    return out


def check_stairs(floors: list[FloorData], pairs: list[dict]) -> list[dict]:
    out = []
    upper = {(p["lower_floor"], p["lower_stair"]): p for p in pairs if p["status"] != "rejected"}
    for i, f in enumerate(floors):
        above = floors[i + 1] if i + 1 < len(floors) else None
        for s in f.stairs:
            if above is None:
                out.append(_issue("stair_no_floor_above", "info",
                                  f"stair {s['id']} on the top floor {f.name!r} has no floor above", [f.id]))
                continue
            if (f.id, s["id"]) not in upper:
                out.append(_issue("stair_unpaired", "warning", f"stair {s['id']} on {f.name!r} is not "
                                  f"paired with a flight on {above.name!r}", [f.id, above.id]))
            gap = above.finished - f.finished
            if s["total_rise"] is not None and abs(s["total_rise"] - gap) > RISE_TOL_MM:
                out.append(_issue("stair_rise_mismatch", "warning",
                                  f"stair {s['id']} on {f.name!r} rises {s['total_rise']:g} mm but the "
                                  f"floor {above.name!r} is {gap:g} mm above", [f.id, above.id]))
    return out


def assemble(db, row: ProjectRow) -> dict:
    mf = sorted(row.data["floors"], key=lambda f: f["elevation"]["value"])
    floors = [_load(db, f) for f in mf]
    pairs, stale = effective_pairings(floors, row.data.get("pairings", []))
    issues = [*check_alignment(floors), *check_stairs(floors, pairs), *stale]
    ok = [f for f in floors if not f.unreadable]
    return {
        "floors": [{
            "id": f.id, "name": f.name, "generation_id": f.generation_id, "roof": f.roof,
            "elevation": f.elevation, "finished_level": f.finished, "top": f.top,
            "offset": {"x": f.offset[0], "y": f.offset[1], "unit": "mm", "source": f.offset_source},
            "bbox": f.bbox, "area_mm2": f.area, "room_count": f.rooms, "stairs": f.stairs,
        } for f in floors],
        "pairings": pairs,
        "issues": issues,
        "stats": {
            "floor_count": len(floors), "room_count": sum(f.rooms for f in floors),
            "total_area_mm2": sum(f.area for f in floors),
            "stair_count": sum(len(f.stairs) for f in floors),
            "height_mm": max((f.top for f in ok), default=0.0) - min((f.elevation for f in ok), default=0.0),
        },
        "_floors": floors,
    }


@public_router.get("/projects/{pid}/building")
def get_building(pid: str, who: Principal):
    with session() as db:
        row = owned(db, ProjectRow, pid, who, "unknown project", need="viewer")
        out = assemble(db, row)
        del out["_floors"]
        v = _latest(db, pid)
        return {"project_id": pid, "version": v.number if v else 0, "role": project_role(db, row, who),
                "materials": row.data.get("materials", {}),
                "lighting": row.data.get("lighting", NO_LIGHTING), **out}


class Offset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(allow_inf_nan=False, ge=-1e7, le=1e7, description="mm")
    y: float = Field(allow_inf_nan=False, ge=-1e7, le=1e7, description="mm")


@router.put("/projects/{pid}/floors/{floor_id}/offset")
def put_offset(pid: str, floor_id: str, req: Offset, user: CurrentUser):
    """Set a floor's manual plan offset (0, 0 resets it to the default); a new version."""
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, user.id, "unknown project", lock=True, need="editor")
        f = _floor(row, floor_id)
        new = {k: v for k, v in f.items() if k != "offset"}
        if (req.x, req.y) != (0, 0):
            new["offset"] = {"x": req.x, "y": req.y, "unit": "mm", "source": "user_provided"}
        row.data = {**row.data, "floors": [new if x["id"] == floor_id else x for x in row.data["floors"]]}
        _version(db, row, user.id, f"Floor {f['name']} offset set to {req.x:g}, {req.y:g} mm")
    return {"id": floor_id, "offset": new.get("offset", {"x": 0, "y": 0, "unit": "mm", "source": "defaulted"})}


class PairRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lower_floor: str
    lower_stair: str
    upper_floor: str
    upper_stair: str


def _save(pid: str, user_id: str, req: PairRef, status: str, message: str) -> dict:
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, user_id, "unknown project", lock=True, need="editor")
        out = assemble(db, row)
        by = {f.id: f for f in out["_floors"]}
        ids = [f.id for f in out["_floors"]]
        lo, up = by.get(req.lower_floor), by.get(req.upper_floor)
        has = lambda f, s: f is not None and any(x["id"] == s for x in f.stairs)
        if not (has(lo, req.lower_stair) and has(up, req.upper_stair)):
            raise HTTPException(404, "unknown stair")
        if ids.index(req.upper_floor) != ids.index(req.lower_floor) + 1:
            raise HTTPException(422, "stairs pair across adjacent floors, lower to upper")
        k = _key(req.model_dump())
        keep = [p for p in out["pairings"] if _key(p) != k and not (
            status == "confirmed" and p["status"] != "rejected" and (
                (p["lower_floor"], p["lower_stair"]) == (req.lower_floor, req.lower_stair)
                or (p["upper_floor"], p["upper_stair"]) == (req.upper_floor, req.upper_stair)))]
        saved = [{k2: p[k2] for k2 in (*_FIELDS, "status")} for p in keep if p["status"] != "auto"]
        saved.append({**req.model_dump(), "status": status})
        row.data = {**row.data, "pairings": saved}
        _version(db, row, user_id, message)
        return {**req.model_dump(), "status": status}


@router.put("/projects/{pid}/building/pairings")
def confirm_pairing(pid: str, req: PairRef, user: CurrentUser):
    """Confirm a pair, or re-pair: it replaces any other pair using either of its stairs."""
    return _save(pid, user.id, req, "confirmed",
                 f"Stairs paired: {req.lower_stair} -> {req.upper_stair}")


@router.post("/projects/{pid}/building/pairings/unpair")
def unpair(pid: str, req: PairRef, user: CurrentUser):
    """Reject a pair so it is not proposed again (confirm it to bring it back)."""
    return _save(pid, user.id, req, "rejected",
                 f"Stairs unpaired: {req.lower_stair} -> {req.upper_stair}")


# Per-element material choice (Phase 1/18): `"<floor id>/<element id>" -> library id`, a project
# setting in the manifest (snapshotted per version). Must match apps/web/public/materials/index.json
# (test_materials checks). Element ids that no longer exist are kept and simply never match.
MATERIAL_IDS = frozenset({"brick", "concrete", "plaster", "paint", "wood-floor", "tile", "timber",
                          "roof-tile", "metal", "stone"})


class MaterialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    materials: dict[str, str] = Field(max_length=5000, description="absent key = default flat colour")


@router.put("/projects/{pid}/materials")
def put_materials(pid: str, req: MaterialsRequest, user: CurrentUser):
    """Replace the project's element -> library material map; a new version."""
    bad = sorted({m for m in req.materials.values() if m not in MATERIAL_IDS})
    if bad or any(not k or len(k) > 200 for k in req.materials):
        raise HTTPException(422, f"unknown material {bad}" if bad else "bad element key")
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, user.id, "unknown project", lock=True, need="editor")
        row.data = {**row.data, "materials": req.materials}
        v = _version(db, row, user.id, f"Materials set on {len(req.materials)} elements")
    return {"materials": req.materials, "version": v.number}


# Lighting setting (Phase 1/19): site location, building north and artificial lights, saved in the
# manifest (snapshotted per version). Date, time, sun intensity and quality are viewer-local, not saved.
# The whole setting is replaced on PUT (last write wins).
class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class ArtificialLight(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    kind: Literal["point", "spot"]
    floor_id: str = Field(min_length=1, max_length=200)
    x_mm: float = Field(ge=-1e7, le=1e7, allow_inf_nan=False, description="plan x, before the floor offset")
    y_mm: float = Field(ge=-1e7, le=1e7, allow_inf_nan=False)
    height_mm: float = Field(ge=0, le=1e5, allow_inf_nan=False, description="above the floor's elevation")
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    intensity: float = Field(ge=0, le=100, allow_inf_nan=False)


class LightingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: Location | None = None
    north_deg: float = Field(0.0, ge=0, lt=360, allow_inf_nan=False,
                             description="clockwise angle from plan +Y to true north")
    lights: list[ArtificialLight] = Field(default_factory=list, max_length=50)


@router.put("/projects/{pid}/lighting")
def put_lighting(pid: str, req: LightingRequest, user: CurrentUser):
    """Replace the project's lighting setting; a new version."""
    if len({x.id for x in req.lights}) != len(req.lights):
        raise HTTPException(422, "duplicate light id")
    lighting = req.model_dump(mode="json")
    with session() as db, db.begin():
        row = owned(db, ProjectRow, pid, user.id, "unknown project", lock=True, need="editor")
        known = {f["id"] for f in row.data["floors"]}
        if any(x.floor_id not in known for x in req.lights):
            raise HTTPException(422, "light on an unknown floor")
        row.data = {**row.data, "lighting": lighting}
        v = _version(db, row, user.id, f"Lighting set ({len(req.lights)} lights)")
    return {"lighting": lighting, "version": v.number}
