"""Wall role (exterior | interior): layer first, geometry as the fallback.

Layer: a wall whose source lines sit on role layers takes that role
(`source_extracted`); lines on conflicting role layers are blocking, never guessed.
Fallback (`inferred`): a wall is exterior when one of its long faces lies on an
exterior ring of the union of all wall and junction footprints, else interior.
Limitation: walls bounding only an interior courtyard (a hole of the union) read
as interior, indistinguishable from a partition without more information.
"""

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from api.engine.adapters.dxf.split import strip_floor_prefix
from api.engine.canonical.model import Issue
from api.engine.geometry2d.walls import JunctionPiece, PairedWall
from api.engine.settings import DEFAULTS, Settings

Role = tuple[str, str]  # (role, role_source)


def _inferred(
    walls: list[PairedWall], junctions: list[JunctionPiece], settings: Settings
) -> dict[str, str]:
    union = unary_union(
        [w.rect() for w in walls] + [Polygon(j.polygon) for j in junctions]
    )
    rings = unary_union(
        [LineString(g.exterior.coords) for g in getattr(union, "geoms", [union])]
    ).buffer(settings.role_face_tolerance_mm)
    out = {}
    for w in walls:
        h = w.thickness / 2
        (x0, y0), (x1, y1) = w.start, w.end
        dx, dy = (0, h) if y0 == y1 else (h, 0)  # offset across the wall
        faces = [
            LineString([(x0 + s * dx, y0 + s * dy), (x1 + s * dx, y1 + s * dy)])
            for s in (-1, 1)
        ]
        out[w.id] = "exterior" if any(rings.covers(f) for f in faces) else "interior"
    return out


def resolve_roles(
    walls: list[PairedWall],
    junctions: list[JunctionPiece],
    settings: Settings = DEFAULTS,
) -> tuple[dict[str, Role | None], list[Issue]]:
    """Role per wall id (None = conflicting layers) plus issues."""
    layer_role = dict(settings.wall_role_layers)
    roles: dict[str, Role | None] = {}
    issues: list[Issue] = []
    pending = []
    for w in walls:
        found = {
            layer_role[strip_floor_prefix(s.layer, settings).upper()]
            for s in w.sources
            if strip_floor_prefix(s.layer, settings).upper() in layer_role
        }
        if len(found) > 1:
            roles[w.id] = None
            issues.append(
                Issue(
                    code="wall_role_conflict",
                    severity="blocking",
                    message=f"{w.id} is drawn on conflicting role layers "
                    f"({', '.join(sorted(found))}); fix the drawing",
                    sources=[s.ref for s in w.sources],
                )
            )
        elif found:
            roles[w.id] = (found.pop(), "source_extracted")
        else:
            pending.append(w)
    if pending:
        inferred = _inferred(walls, junctions, settings)
        for w in pending:
            roles[w.id] = (inferred[w.id], "inferred")
        issues.append(
            Issue(
                code="wall_role_inferred",
                severity="warning",
                message=f"{len(pending)} wall(s) have no role layer "
                f"({', '.join(l for l, _ in settings.wall_role_layers)}); role "
                "inferred from geometry (a face on the outer boundary of all walls "
                "= exterior). Walls around an interior courtyard read as interior.",
                sources=list(dict.fromkeys(s.ref for w in pending for s in w.sources)),
            )
        )
    return roles, issues
