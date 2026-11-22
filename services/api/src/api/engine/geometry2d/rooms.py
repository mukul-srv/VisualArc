"""Rooms: closed regions enclosed by the wall graph, named by TEXT/MTEXT labels inside them.

Wall rectangles plus junction fills are unioned; every hole of that union is a closed region.
A region the walls do not close is never found here, so a label that lies in no region is
reported (the usual sign of an open outline), as is a wall graph that encloses nothing.
Openings do not split walls, so doors and windows never open a room.
"""

from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from api.engine.canonical.model import Issue, Point2, SourceRef
from api.engine.geometry2d.walls import JunctionPiece, PairedWall, _ring
from api.engine.settings import DEFAULTS, Settings


@dataclass(frozen=True)
class Label:
    text: str
    point: Point2  # plan mm
    ref: SourceRef


@dataclass(frozen=True)
class RoomPiece:
    id: str
    name: str
    name_from_label: bool
    polygon: list[Point2]
    holes: list[list[Point2]]  # free-standing wall pieces inside; the area excludes them
    area: float  # mm2, to the inner wall faces
    labels: list[Label]  # every label inside, in reading order


def _reading(lab: Label) -> tuple[float, float]:
    return (-lab.point[1], lab.point[0])  # top to bottom, then left to right (plan y is up)


def _where(lab: Label) -> str:
    return f"{lab.text!r} at ({lab.point[0]:g}, {lab.point[1]:g})"


def _open_ends(
    walls: list[PairedWall], pieces: list[JunctionPiece], settings: Settings
) -> list[Issue]:
    """Wall ends not joined to any other wall or junction: the outline is open there, so no
    room closes through it (a room elsewhere may still close)."""
    tol, free = settings.tolerance_mm, []
    for w in walls:
        others = unary_union(
            [v.rect() for v in walls if v.id != w.id] + [Polygon(j.polygon) for j in pieces]
        )
        h = w.thickness / 2
        y0, y1 = w.start[1], w.end[1]
        horizontal = y0 == y1
        for x, y in (w.start, w.end):
            cap = LineString([(x, y - h), (x, y + h)] if horizontal else [(x - h, y), (x + h, y)])
            if cap.intersection(others).length < w.thickness - tol:
                free.append((w, (x, y)))
    if not free:
        return []
    cap_n = settings.unmapped_ref_cap
    return [Issue(
        code="room_outline_open", severity="warning",
        message=f"{len(free)} wall end(s) are not joined to another wall, so the outline is open "
        "there and no room closes through them: "
        + "; ".join(f"{w.id} end at ({p[0]:g}, {p[1]:g})" for w, p in free[:cap_n])
        + ("; ..." if len(free) > cap_n else ""),
        sources=list(dict.fromkeys(s.ref for w, _ in free[:cap_n] for s in w.sources)),
    )]


def find_rooms(
    walls: list[PairedWall],
    pieces: list[JunctionPiece],
    labels: list[Label],
    settings: Settings = DEFAULTS,
) -> tuple[list[RoomPiece], list[Issue]]:
    tol = settings.tolerance_mm
    union = unary_union([w.rect() for w in walls] + [Polygon(j.polygon) for j in pieces])
    polys = [g for g in getattr(union, "geoms", [union]) if isinstance(g, Polygon)]
    regions: list[Polygon] = []
    issues: list[Issue] = []
    for poly in polys:
        for ring in poly.interiors:
            hole = Polygon(ring)
            islands = [q for q in polys if q is not poly and hole.contains(q)]
            region = hole.difference(unary_union(islands)) if islands else hole
            if isinstance(region, Polygon) and region.area <= tol:
                continue  # numerical sliver
            if not isinstance(region, Polygon):
                x0, y0, x1, y1 = hole.bounds
                issues.append(Issue(
                    code="room_region_unusable", severity="warning",
                    message=f"closed region {x0:.1f},{y0:.1f}..{x1:.1f},{y1:.1f} is not a single "
                    "area once its free-standing wall pieces are removed; no room built for it",
                ))
                continue
            if islands:
                x0, y0, x1, y1 = hole.bounds
                issues.append(Issue(
                    code="room_has_obstruction", severity="warning",
                    message=f"closed region {x0:.1f},{y0:.1f}..{x1:.1f},{y1:.1f} holds "
                    f"{len(islands)} free-standing wall piece(s); their area is excluded from the room",
                ))
            regions.append(region)
    regions.sort(key=lambda g: (g.bounds[1], g.bounds[0]))
    issues += _open_ends(walls, pieces, settings)
    if not regions:
        issues.append(Issue(
            code="no_closed_rooms", severity="warning",
            message="the walls enclose no closed region, so no rooms were built; "
            "check that wall outlines close",
        ))

    inside: dict[int, list[Label]] = {i: [] for i in range(len(regions))}
    lost = []
    for lab in labels:
        hit = next((i for i, g in enumerate(regions) if g.contains(Point(lab.point))), None)
        (lost if hit is None else inside[hit]).append(lab)
    if lost:
        cap = settings.unmapped_ref_cap
        issues.append(Issue(
            code="room_label_unplaced", severity="warning",
            message=f"{len(lost)} text label(s) lie in no closed room (open outline, or outside "
            "the walls): " + "; ".join(_where(x) for x in lost[:cap]) + ("; ..." if len(lost) > cap else ""),
            sources=[x.ref for x in lost[:cap]],
        ))

    rooms, unnamed = [], []
    for i, g in enumerate(regions):
        rid, labs = f"room-{i + 1:03d}", sorted(inside[i], key=_reading)
        if labs:
            name = labs[0].text
            if len(labs) > 1:
                issues.append(Issue(
                    code="room_name_ambiguous", severity="warning",
                    message=f"{rid} holds {len(labs)} labels ({'; '.join(_where(x) for x in labs)}); "
                    f"named {name!r}, the first in reading order",
                    sources=[x.ref for x in labs],
                ))
        else:
            name = f"Room {i + 1}"
            unnamed.append(name)
        holes = [_ring(Polygon(h)) for h in g.interiors]
        rooms.append(RoomPiece(rid, name, bool(labs), _ring(Polygon(g.exterior)), holes, g.area, labs))
    if unnamed:
        issues.append(Issue(
            code="room_name_defaulted", severity="warning",
            message=f"no label inside {', '.join(unnamed)}; numbered names assumed",
        ))
    return rooms, issues
