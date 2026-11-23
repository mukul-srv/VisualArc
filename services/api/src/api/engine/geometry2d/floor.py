"""Floor boundary validity: a floor we cannot trust is blocking, never repaired."""

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.validation import explain_validity

from api.engine.canonical.model import Issue, Point2, SourceRef
from api.engine.settings import DEFAULTS, Settings


def closed_outer_perimeter(walls, junctions, settings: Settings = DEFAULTS) -> Polygon | None:
    """The area inside the closed OUTER wall loop of the building, or None when the outer walls do not close.
    The outer walls are those with a face on the outer boundary of all walls (as in wall roles). They
    close when, with the corner fills, they enclose an area themselves: an open outer wall leaves a C that
    encloses nothing, however many closed rooms the partitions make inside."""
    rects = {w.id: w.rect() for w in walls}
    pieces = [Polygon(j.polygon) for j in junctions]
    # the building is the connected wall mass with the largest extent (walls that only touch at a corner
    # still connect); a smaller closed box of walls (a detached room inside or beside it) is not its
    # perimeter, so it cannot stand in for an open outer wall
    grow = settings.role_face_tolerance_mm
    grown = unary_union([g.buffer(grow) for g in [*rects.values(), *pieces]])
    parts = [g for g in getattr(grown, "geoms", [grown]) if isinstance(g, Polygon)]
    building = max(parts, key=lambda g: g.convex_hull.area)
    mine = {w.id: r for w, r in zip(walls, rects.values(), strict=True) if r.intersects(building)}
    mine_pieces = [g for g in pieces if g.intersects(building)]
    union = unary_union([*mine.values(), *mine_pieces])
    rings = unary_union([LineString(g.exterior.coords) for g in getattr(union, "geoms", [union])]).buffer(grow)
    outer = []
    for w in walls:
        if w.id not in mine:
            continue
        h = w.thickness / 2
        (x0, y0), (x1, y1) = w.start, w.end
        dx, dy = (0, h) if y0 == y1 else (h, 0)
        if any(rings.covers(LineString([(x0 + s * dx, y0 + s * dy), (x1 + s * dx, y1 + s * dy)])) for s in (-1, 1)):
            outer.append(mine[w.id])
    outer += [g for g in mine_pieces if g.intersects(rings)]
    mass = unary_union(outer)
    holes = [Polygon(r) for g in getattr(mass, "geoms", [mass]) if isinstance(g, Polygon) for r in g.interiors]
    holes = [h for h in holes if h.area > settings.tolerance_mm]
    return unary_union(holes) if holes else None


def floor_issue(
    pts: list[Point2], ref: SourceRef, settings: Settings = DEFAULTS
) -> Issue | None:
    """Blocking issue if the ring self-intersects or has no area; winding is irrelevant."""
    poly = Polygon(pts)
    if poly.is_valid and poly.area > settings.tolerance_mm:
        return None
    reason = (
        explain_validity(poly)
        if not poly.is_valid
        else f"area {poly.area:.3f} mm2 is not positive"
    )
    return Issue(
        code="invalid_floor_boundary",
        severity="blocking",
        message=f"floor polyline {ref.entity_handle} is not a valid polygon "
        f"({reason}); excluded",
        sources=[ref],
    )
