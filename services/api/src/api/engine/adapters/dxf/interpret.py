"""Smarter interpretation of DXF input (26a).

- DIMENSION check: only observes and suggests. A units suggestion is never applied; the user confirms it
  through the units choice.
- Block symbols: `classify_block` only classifies. The reader then PLACES what is recognised (a door/window
  marker or a stair outline from the block's bounding box) and reports every placement, with a confirm/remove
  suggestion when it rests on geometry alone. What is only a candidate is reported with a layer-role
  suggestion and not placed."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

import ezdxf

from api.engine.canonical.model import Issue, SourceRef, Suggestion
from api.engine.settings import DEFAULTS, Settings

UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}


_TEXT = re.compile(r"""^\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m|in|ft|"|')?\s*$""", re.IGNORECASE)
_SUFFIX = {"mm": "mm", "cm": "cm", "m": "m", "in": "in", '"': "in", "ft": "ft", "'": "ft"}
_TEXT_UNITS = ((10.0, "cm"), (25.4, "in"), (304.8, "ft"), (1000.0, "m"))


def _parse(text: str) -> tuple[float, str | None] | None:
    """Dimension text -> (number, unit suffix or None), or None when it is not a plain number with an
    optional unit (feet-inches, fractions, prefixes and the like are not read)."""
    m = _TEXT.match(text)
    return None if m is None else (float(m.group(1).replace(",", ".")), _SUFFIX[m.group(2).lower()] if m.group(2) else None)


def dimension_check(entities, k: float, settings: Settings = DEFAULTS) -> list[Issue]:
    """Compare each linear/aligned DIMENSION's stated value (text override with an optional unit suffix, else
    the stored measurement, which has no unit) with the length between its definition points. A value
    without a suffix is read as mm. Issues, all warnings, nothing is changed:
    - `dimension_scale_mismatch` when most dimensions disagree (names the unit that explains them, if any);
    - `dimension_unit_interpreted` when a unitless value only fits if its text is cm/in/ft/m (the unit it
      was read as is named; accepted only while the drawn length is a plausible plan size);
    - `dimension_text_unreadable` (one issue, with the count) for text that is not a number with a unit.
    Angular, radial and ordinate dimensions are not read."""
    tol, hi = settings.dimension_rel_tolerance, settings.plausible_footprint_mm[1]
    bad: list[tuple[SourceRef, set[str]]] = []
    alt: dict[str, list[SourceRef]] = {}
    unreadable: list[SourceRef] = []
    seen = 0
    for e in entities:
        if e.dxftype() != "DIMENSION":
            continue
        try:
            if e.dimtype not in (0, 1) or not (e.dxf.hasattr("defpoint2") and e.dxf.hasattr("defpoint3")):
                continue
            ref = SourceRef(layer=e.dxf.layer, entity_handle=e.dxf.handle)
            p, q = e.dxf.defpoint2, e.dxf.defpoint3
            raw = math.dist((p.x, p.y), (q.x, q.y))
            if e.dimtype == 0:  # linear: measured along the dimension angle
                a = math.radians(e.dxf.get("angle", 0.0))
                raw = abs((q.x - p.x) * math.cos(a) + (q.y - p.y) * math.sin(a))
            text = e.dxf.get("text", "")
            value, unit = None, None
            if text.strip() and "<>" not in text:
                parsed = _parse(text)
                if parsed is None:
                    unreadable.append(ref)
                    continue
                value, unit = parsed
            elif not text.strip("<> "):
                value = e.dxf.get("actual_measurement", 0.0) or None
        except (AttributeError, ValueError, TypeError, ezdxf.DXFError):
            continue
        stated = None if value is None else value * UNIT_MM[unit or "mm"]
        if stated is None or stated <= 0 or raw * k < settings.dimension_min_mm:
            continue
        seen += 1
        geom = raw * k
        if abs(geom - stated) <= tol * stated + 1.0:
            continue
        found = None if unit else next(
            (n for f, n in _TEXT_UNITS if geom <= hi and abs(geom - stated * f) <= tol * stated * f + 1.0), None)
        if found:
            alt.setdefault(found, []).append(ref)
            continue
        bad.append((ref, {u for u, f in UNIT_MM.items() if abs(raw * f - stated) <= tol * stated + 1.0}))
    cap, issues = settings.unmapped_ref_cap, []
    if bad and len(bad) * 2 > seen:
        votes = Counter(u for _, us in bad for u in us)
        best = votes.most_common(1)[0][0] if votes else None
        msg = (f"{len(bad)} of {seen} DIMENSION values do not match the length between their "
               f"definition points at the current scale (tolerance {tol:.0%}); the drawing units may be wrong")
        sug = []
        if best is not None and votes[best] == len(bad):
            factor = UNIT_MM[best] / k
            msg += f". The values fit units {best} (scale factor x{factor:g})"
            sug = [Suggestion(kind="units", value=best, label=f"choose units {best} (scale factor x{factor:g})")]
        issues.append(Issue(code="dimension_scale_mismatch", severity="warning",
                            message=msg + "; nothing was changed, confirm by choosing the real units",
                            sources=[r for r, _ in bad[:cap]], suggestions=sug))
    for name, refs in alt.items():
        issues.append(Issue(
            code="dimension_unit_interpreted", severity="warning",
            message=f"{len(refs)} DIMENSION value(s) without a unit only match the drawing if their text is in "
            f"{name} (not mm); they were read as {name}. Check the dimension style units; nothing was changed",
            sources=refs[:cap]))
    if unreadable:
        issues.append(Issue(
            code="dimension_text_unreadable", severity="warning",
            message=f"{len(unreadable)} DIMENSION text(s) are not a plain number with an optional unit "
            "(mm, cm, m, in, ft) and were not compared with the drawing",
            sources=unreadable[:cap]))
    return issues


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


def classify_block(entities, name: str, scale: float, settings: Settings = DEFAULTS) -> Recognition | None:
    """What a block DEFINITION looks like (its own entities, before any INSERT rotation; `scale` = mm per
    block unit), or None when it is no recognisable symbol. Door: one quarter-turn ARC plus a leaf line from
    its centre to an end (length = radius). Window: several parallel equal-extent lines packed within a wall
    thickness, no arc. Stair: a run of equally spaced parallel lines. A name hint (door/window/stair words)
    is evidence of its own."""
    up = name.upper()
    hint = next((r for w, r in settings.block_name_hints if w in up), None)
    arcs, segs = [v for v in entities if v.dxftype() == "ARC"], _segments(entities)
    hit = None
    if len(arcs) == 1 and segs and _door(arcs[0], segs, settings):
        hit = ("door", "swing arc with a leaf line from its centre")
    elif not arcs:
        hit = _parallel_run(segs, scale, settings)
    if hit is None and hint is None:
        return None
    return Recognition(
        hit[0] if hit else None, hint,
        f"geometry: {hit[1] if hit else 'no known symbol shape'}; "
        f"{'name suggests ' + hint if hint else 'name gives no hint'}",
    )
