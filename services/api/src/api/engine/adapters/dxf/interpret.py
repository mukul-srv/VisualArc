"""Smarter interpretation of DXF input (26a): a units sanity check from DIMENSION entities and
recognition of door/window/stair block symbols. Everything here only OBSERVES and SUGGESTS: a
suggestion is never applied, the user confirms it through the units choice or the layer mapping."""

import math
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

import ezdxf

from api.engine.canonical.model import Issue, SourceRef, Suggestion
from api.engine.settings import DEFAULTS, Settings

UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
_TEXT_FACTORS = (10.0, 25.4, 304.8, 1000.0)  # dimension text in cm / in / ft / m is also consistent


def _num(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


def dimension_check(entities, k: float, settings: Settings = DEFAULTS) -> list[Issue]:
    """Compare each linear/aligned DIMENSION's stated value (numeric text override, else the stored
    measurement) with the length between its definition points. The stated value is assumed to be mm.
    One warning when most dimensions disagree; it names the unit that explains them, if one does.
    Shortcut: text in cm/in/ft/m is accepted only while the drawn length stays a plausible plan size;
    angular, radial and ordinate dimensions are not read."""
    tol, hi = settings.dimension_rel_tolerance, settings.plausible_footprint_mm[1]
    bad: list[tuple[SourceRef, set[str]]] = []
    seen = 0
    for e in entities:
        if e.dxftype() != "DIMENSION":
            continue
        try:
            if e.dimtype not in (0, 1) or not (e.dxf.hasattr("defpoint2") and e.dxf.hasattr("defpoint3")):
                continue
            p, q = e.dxf.defpoint2, e.dxf.defpoint3
            raw = math.dist((p.x, p.y), (q.x, q.y))
            if e.dimtype == 0:  # linear: measured along the dimension angle
                a = math.radians(e.dxf.get("angle", 0.0))
                raw = abs((q.x - p.x) * math.cos(a) + (q.y - p.y) * math.sin(a))
            text = e.dxf.get("text", "")
            stated = None
            if text.strip() and "<>" not in text:
                stated = _num(text)
            elif not text.strip() or not text.strip("<> "):
                stated = e.dxf.get("actual_measurement", 0.0) or None
        except (AttributeError, ValueError, TypeError, ezdxf.DXFError):
            continue
        if stated is None or stated <= 0 or raw * k < settings.dimension_min_mm:
            continue
        seen += 1
        geom = raw * k
        if abs(geom - stated) <= tol * stated + 1.0:
            continue
        if geom <= hi and any(abs(geom - stated * f) <= tol * stated * f + 1.0 for f in _TEXT_FACTORS):
            continue
        units = {u for u, f in UNIT_MM.items() if abs(raw * f - stated) <= tol * stated + 1.0}
        bad.append((SourceRef(layer=e.dxf.layer, entity_handle=e.dxf.handle), units))
    if not bad or len(bad) * 2 <= seen:
        return []
    votes = Counter(u for _, us in bad for u in us)
    best = votes.most_common(1)[0][0] if votes else None
    msg = (f"{len(bad)} of {seen} DIMENSION values (read as mm) do not match the length between their "
           f"definition points at the current scale (tolerance {tol:.0%}); the drawing units may be wrong")
    sug = []
    if best is not None and votes[best] == len(bad):
        factor = UNIT_MM[best] / k
        msg += f". The values fit units {best} (scale factor x{factor:g})"
        sug = [Suggestion(kind="units", value=best, label=f"choose units {best} (scale factor x{factor:g})")]
    return [Issue(code="dimension_scale_mismatch", severity="warning",
                  message=msg + "; nothing was changed, confirm by choosing the real units",
                  sources=[r for r, _ in bad[: settings.unmapped_ref_cap]], suggestions=sug)]


# --- block symbols -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Recognition:
    geometry: str | None  # kind the geometry shows
    name: str | None  # kind the block name suggests
    why: str

    @property
    def confident(self) -> bool:
        """Geometry and name agree, or a door/window shows only its geometry. Stairs need both."""
        if self.geometry and self.name:
            return self.geometry == self.name
        return self.geometry in ("door", "window")

    @property
    def kind(self) -> str | None:
        return self.geometry or self.name

    @property
    def candidates(self) -> list[str]:
        return list(dict.fromkeys(x for x in (self.geometry, self.name) if x))


def _segments(ents) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    out = []
    for v in ents:
        if v.dxftype() == "LINE":
            out.append(((v.dxf.start.x, v.dxf.start.y), (v.dxf.end.x, v.dxf.end.y)))
        elif v.dxftype() == "LWPOLYLINE" and not any(b for *_, b in v.get_points("xyb")):
            pts = [(p[0], p[1]) for p in v.get_points("xy")]
            out += list(pairwise(pts + pts[:1] if v.closed else pts))
    return [s for s in out if math.dist(*s) > 0]


def _door(arc, segs, settings: Settings) -> bool:
    t = arc.construction_tool()
    lo, hi = settings.block_swing_span_deg
    if not lo <= (t.end_angle - t.start_angle) % 360 <= hi:
        return False
    c, r = (arc.dxf.center.x, arc.dxf.center.y), arc.dxf.radius
    tol = settings.block_rel_tolerance * r
    ends = [(t.start_point.x, t.start_point.y), (t.end_point.x, t.end_point.y)]
    return any(
        math.dist(a, c) <= tol and abs(math.dist(a, b) - r) <= tol and any(math.dist(b, en) <= tol for en in ends)
        for s in segs for a, b in (s, s[::-1])
    )


def _parallel_run(segs, k: float, settings: Settings) -> tuple[str, str] | None:
    rel = settings.block_rel_tolerance
    for axis in (0, 1):  # lines along x (constant y) or along y (constant x)
        par = [s for s in segs if abs(s[0][1 - axis] - s[1][1 - axis]) <= 1e-9 * max(1.0, abs(s[0][1 - axis]))]
        if len(par) < settings.block_min_parallel_lines:
            continue
        ext = [(min(s[0][axis], s[1][axis]), max(s[0][axis], s[1][axis])) for s in par]
        length = max(b - a for a, b in ext)
        if any(abs((b - a) - length) > rel * length or abs(a - ext[0][0]) > rel * length for a, b in ext):
            continue  # not of equal extent, or not side by side
        offs = sorted({round(s[0][1 - axis], 9) for s in par})
        spread, gaps = (offs[-1] - offs[0]) * k, [b - a for a, b in pairwise(offs)]
        if len(offs) >= settings.block_min_treads and spread > settings.wall_thickness_max_mm and all(
            abs(g - gaps[0]) <= rel * gaps[0] for g in gaps
        ):
            return "stair", f"{len(offs)} equally spaced parallel lines (a tread run)"
        if len(offs) >= settings.block_min_parallel_lines and 0 < spread <= settings.wall_thickness_max_mm:
            return "window", f"{len(offs)} parallel equal lines within {spread:g} mm"
    return None


def classify_block(e, k: float, settings: Settings = DEFAULTS) -> Recognition | None:
    """What an INSERT looks like, or None when it is no recognisable symbol. Door: one quarter-turn ARC
    plus a leaf line from its centre to an end (length = radius). Window: several parallel equal-extent
    lines packed within a wall thickness, no arc. Stair: a run of equally spaced parallel lines. A name
    hint (door/window/stair words) is evidence of its own."""
    try:
        ents = list(e.virtual_entities())
    except (ValueError, TypeError, AttributeError, ezdxf.DXFError):
        return None
    up = e.dxf.name.upper()
    name = next((r for w, r in settings.block_name_hints if w in up), None)
    arcs, segs = [v for v in ents if v.dxftype() == "ARC"], _segments(ents)
    hit = None
    if len(arcs) == 1 and segs and _door(arcs[0], segs, settings):
        hit = ("door", "swing arc with a leaf line from its centre")
    elif not arcs:
        hit = _parallel_run(segs, k, settings)
    if hit is None and name is None:
        return None
    return Recognition(
        hit[0] if hit else None, name,
        f"geometry: {hit[1] if hit else 'no known symbol shape'}; "
        f"{'name suggests ' + name if name else 'name gives no hint'}",
    )
