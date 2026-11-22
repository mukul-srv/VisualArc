"""Balconies/terraces: closed outlines on the balcony layer, outside the building's rooms.

An outline that overlaps a room, or touches no wall, is still built (the drawing says it is a
balcony) but reported; the railing runs along the outline edges the building walls do not cover.
"""

from dataclasses import dataclass
from itertools import pairwise

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

from api.engine.canonical.model import Issue, LineGeometry, Point2, SourceRef
from api.engine.geometry2d.walls import JunctionPiece, PairedWall
from api.engine.settings import DEFAULTS, Settings


@dataclass(frozen=True)
class BalconyPiece:
    id: str
    polygon: list[Point2]
    railings: list[LineGeometry]
    ref: SourceRef


def _on(building, p: Point2, tol: float) -> Point2:
    """The cut end sits `tol` short of the wall; put it back exactly on the wall face."""
    if building.distance(Point(p)) <= 2 * tol:
        q = nearest_points(building, Point(p))[0]
        return (q.x, q.y)
    return (p[0], p[1])


def _free_edges(poly: Polygon, building, tol: float) -> list[LineGeometry]:
    """Outline pieces farther than `tol` from the building walls (exact match, no snapping)."""
    covered = building.buffer(tol)
    out = []
    ring = list(poly.exterior.coords)
    for a, b in pairwise(ring):
        rest = LineString([a, b]).difference(covered)
        for g in getattr(rest, "geoms", [rest]):
            if isinstance(g, LineString) and not g.is_empty and g.length > tol:
                out.append(LineGeometry(start=_on(building, g.coords[0], tol),
                                        end=_on(building, g.coords[-1], tol)))
    return out


def find_balconies(
    outlines: list[tuple[SourceRef, list[Point2]]],
    walls: list[PairedWall],
    pieces: list[JunctionPiece],
    rooms: list[list[Point2]],
    settings: Settings = DEFAULTS,
) -> tuple[list[BalconyPiece], list[Issue]]:
    tol = settings.tolerance_mm
    building = unary_union(
        [w.rect() for w in walls] + [Polygon(j.polygon) for j in pieces]
    )
    room_area = unary_union([Polygon(r) for r in rooms])
    found, issues = [], []
    ordered = sorted(outlines, key=lambda o: (min(y for _, y in o[1]), min(x for x, _ in o[1])))
    for n, (ref, pts) in enumerate(ordered, 1):
        poly = Polygon(pts)
        bid = f"balcony-{n:03d}"
        if poly.intersection(room_area).area > tol:
            issues.append(Issue(
                code="balcony_overlaps_room", severity="warning",
                message=f"{bid} (outline {ref.entity_handle}) overlaps a room, so it is not "
                "outside the wall outline; built as drawn, check the layer",
                sources=[ref],
            ))
        if building.is_empty or poly.distance(building) > tol:
            issues.append(Issue(
                code="balcony_detached", severity="warning",
                message=f"{bid} (outline {ref.entity_handle}) touches no wall, so it is not "
                "attached to the building; built as drawn",
                sources=[ref],
            ))
        found.append(BalconyPiece(bid, pts, _free_edges(poly, building, tol), ref))
    return found, issues
