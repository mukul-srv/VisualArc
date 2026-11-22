"""Roof planning: which outlines get a roof and of which kind, with fallbacks that are reported.

Outlines are the closed polygons on the roof-plan layer when there are any, else the exterior of
the union of walls, junctions and floor boundaries (one per detached part). Gable and hip need an
axis-aligned rectangle; anything else, a square gable (ridge direction unknown) or a pitch that
is missing or not above 0 falls back to a flat roof with an issue, never silently.
"""

import math
from dataclasses import dataclass

from shapely.geometry import Polygon

from api.engine.canonical.model import Issue, Point2, SourceRef
from api.engine.geometry2d.openings import marker_rect
from api.engine.settings import DEFAULTS, Settings


@dataclass(frozen=True)
class Outline:
    polygon: list[Point2]
    source: str  # "roof_layer" | "walls"
    refs: list[SourceRef]
    holes: tuple = ()  # enclosed rings of the wall union (rooms, courtyards); roofs ignore them


@dataclass(frozen=True)
class RoofPlan:
    id: str
    kind: str  # built
    requested: str
    outline: Outline
    rect: tuple[float, float, float, float] | None  # pitched only: the outline's rectangle
    ridge_axis: str | None


def wall_outlines(shapes: list[Polygon], settings: Settings = DEFAULTS) -> list[Outline]:
    """Exterior ring of each connected part of the union of `shapes` (holes = rooms are roofed)."""
    from shapely.ops import unary_union

    u = unary_union(shapes)
    out = []
    for g in getattr(u, "geoms", [u]):
        if isinstance(g, Polygon) and g.area > settings.tolerance_mm:
            ring = list(g.simplify(0).exterior.coords)[:-1]
            holes = tuple(list(i.coords)[:-1] for i in g.interiors)
            out.append(Outline(ring, "walls", [], holes))
    return out


def plan_roofs(
    outlines: list[Outline],
    requested: str,
    pitch: float | None,
    settings: Settings = DEFAULTS,
) -> tuple[list[RoofPlan], list[Issue]]:
    tol, issues, plans = settings.tolerance_mm, [], []
    ordered = sorted(outlines, key=lambda o: (min(y for _, y in o.polygon), min(x for x, _ in o.polygon)))
    for a, b in ((a, b) for i, a in enumerate(ordered) for b in ordered[i + 1 :]):
        if Polygon(a.polygon).intersection(Polygon(b.polygon)).area > tol:
            issues.append(Issue(
                code="roof_outlines_overlap", severity="warning",
                message="two roof outlines overlap; both built as drawn",
                sources=[*a.refs, *b.refs],
            ))
    for n, o in enumerate(ordered, 1):
        rid, kind, rect, axis, why = f"roof-{n:03d}", requested, None, None, None
        if requested != "flat":
            rect = marker_rect(o.polygon, tol)
            if pitch is None:
                why = ("roof_pitch_unknown", "no roof pitch (choose a building type or set the parameter)")
            elif not 0 < pitch < 90:
                why = ("roof_pitch_invalid", f"roof pitch {pitch:g} deg is not above 0 and below 90")
            elif rect is None:
                why = ("roof_shape_unsupported", f"the outline is not an axis-aligned rectangle, which {requested} roofs need")
            elif requested == "gable" and abs((rect[2] - rect[0]) - (rect[3] - rect[1])) <= tol:
                why = ("roof_ridge_ambiguous", "the outline is square, so the gable ridge direction is unknown")
            if why:
                issues.append(Issue(
                    code=why[0], severity="warning",
                    message=f"{rid}: {why[1]}; built as a flat roof instead",
                    sources=o.refs,
                ))
                kind, rect = "flat", None
            else:
                axis = "x" if rect[2] - rect[0] >= rect[3] - rect[1] else "y"
        plans.append(RoofPlan(rid, kind, requested, o, rect, axis))
    return plans, issues


def ridge_height(span: float, pitch_deg: float) -> float:
    """Rise of the ridge above the eaves plane: half the span x tan(pitch)."""
    return span / 2 * math.tan(math.radians(pitch_deg))
