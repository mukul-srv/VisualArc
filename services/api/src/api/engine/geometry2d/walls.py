"""Paired-line wall detection for orthogonal walls (MVP-0 convention).

Input: wall boundary segments in mm. Output: walls (centreline + thickness from
the distance between two parallel face lines), inferred junction pieces filling
L/T corners, and Issues. Never guesses: ambiguous pairings are blocking.
"""

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from api.engine.canonical.model import Issue, Point2, SourceRef

TOL = 1e-6  # mm
THK_MIN, THK_MAX = 50.0, 600.0  # plausible wall thickness range, mm


@dataclass(frozen=True)
class Segment:
    handle: str
    layer: str
    start: Point2
    end: Point2

    @property
    def ref(self) -> SourceRef:
        return SourceRef(layer=self.layer, entity_handle=self.handle)


@dataclass(frozen=True, eq=False)  # identity hash: polyline pieces share a handle
class _Axial:
    seg: Segment
    axis: str  # "h" = constant y, "v" = constant x
    c: float  # the constant coordinate
    lo: float
    hi: float


@dataclass(frozen=True)
class PairedWall:
    id: str
    start: Point2
    end: Point2
    thickness: float
    sources: tuple[Segment, Segment]

    def rect(self) -> Polygon:
        h = self.thickness / 2
        (x0, y0), (x1, y1) = self.start, self.end
        if y0 == y1:  # horizontal
            return box(x0, y0 - h, x1, y0 + h)
        return box(x0 - h, y0, x0 + h, y1)


@dataclass(frozen=True)
class JunctionPiece:
    id: str
    polygon: list[Point2]
    wall_ids: list[str]


def _axial(s: Segment) -> _Axial | None:
    (x0, y0), (x1, y1) = s.start, s.end
    if abs(y1 - y0) <= TOL:
        return _Axial(s, "h", (y0 + y1) / 2, min(x0, x1), max(x0, x1))
    if abs(x1 - x0) <= TOL:
        return _Axial(s, "v", (x0 + x1) / 2, min(y0, y1), max(y0, y1))
    return None


def _usable(segments: list[Segment]) -> tuple[list[_Axial], list[Issue]]:
    axial, issues = [], []
    for s in segments:
        if math.dist(s.start, s.end) <= TOL:
            issues.append(
                Issue(
                    code="degenerate_segment",
                    severity="warning",
                    message=f"zero-length wall segment {s.handle} ignored",
                    sources=[s.ref],
                )
            )
        elif (a := _axial(s)) is None:
            issues.append(
                Issue(
                    code="non_orthogonal_segment",
                    severity="warning",
                    message=f"segment {s.handle} is not orthogonal; "
                    "unsupported in MVP-0, ignored",
                    sources=[s.ref],
                )
            )
        else:
            axial.append(a)
    return axial, issues


def pair_walls(
    segments: list[Segment], thk_min: float = THK_MIN, thk_max: float = THK_MAX
) -> tuple[list[PairedWall], list[Issue]]:
    axial, issues = _usable(segments)

    cands: dict[_Axial, list[_Axial]] = {a: [] for a in axial}
    for i, a in enumerate(axial):
        for b in axial[i + 1 :]:
            if a.axis != b.axis:
                continue
            if not thk_min - TOL <= abs(a.c - b.c) <= thk_max + TOL:
                continue
            if min(a.hi, b.hi) - max(a.lo, b.lo) <= TOL:
                continue
            cands[a].append(b)
            cands[b].append(a)

    # One long face pairing with several split faces at the same offset is fine.
    # Partners at different offsets (or on both sides) means we cannot tell which
    # lines form the wall -> blocking, never a guess.
    ambiguous = set()
    for a in axial:
        offsets = [b.c - a.c for b in cands[a]]
        if any(abs(o - offsets[0]) > TOL for o in offsets):
            ambiguous.add(a)
            issues.append(
                Issue(
                    code="ambiguous_pairing",
                    severity="blocking",
                    message=f"segment {a.seg.handle} has parallel partners at different "
                    f"offsets {sorted({round(o, 3) for o in offsets})} mm",
                    sources=[a.seg.ref] + [b.seg.ref for b in cands[a]],
                )
            )
        elif not offsets:
            issues.append(
                Issue(
                    code="unpaired_segment",
                    severity="warning",
                    message=f"segment {a.seg.handle} has no parallel partner "
                    f"within {thk_min}-{thk_max} mm",
                    sources=[a.seg.ref],
                )
            )

    idx = {a: i for i, a in enumerate(axial)}
    raw = []
    for a in axial:
        for b in cands[a]:
            if idx[b] < idx[a] or a in ambiguous or b in ambiguous:
                continue
            lo, hi = max(a.lo, b.lo), min(a.hi, b.hi)
            mid = (a.c + b.c) / 2
            start, end = (
                ((lo, mid), (hi, mid)) if a.axis == "h" else ((mid, lo), (mid, hi))
            )
            lower, upper = sorted((a, b), key=lambda s: s.c)
            raw.append((start, end, abs(a.c - b.c), (lower.seg, upper.seg)))

    raw.sort(key=lambda r: (r[0][1], r[0][0], r[1][1], r[1][0]))
    walls = [PairedWall(f"wall-{n:03d}", *r) for n, r in enumerate(raw, 1)]
    return walls, issues


def _ring(p: Polygon) -> list[Point2]:
    """CCW exterior ring, collinear points dropped, starting at the min vertex."""
    pts = list(orient(p.simplify(0), 1.0).exterior.coords)[:-1]
    k = pts.index(min(pts))
    return pts[k:] + pts[:k]


def find_junctions(
    segments: list[Segment], walls: list[PairedWall], thk_max: float = THK_MAX
) -> tuple[list[JunctionPiece], list[Issue]]:
    """Fill regions enclosed by wall lines that no wall rectangle covers.

    Faces of the noded wall-line arrangement that overlap a wall rectangle are wall
    material; material minus wall rectangles = corner/T gaps.
    """
    if not walls:
        return [], []
    axial, _ = _usable(segments)  # issues already reported by pair_walls
    rects = {w.id: w.rect() for w in walls}
    covered = unary_union(list(rects.values()))
    faces = polygonize(
        unary_union([LineString([a.seg.start, a.seg.end]) for a in axial])
    )
    material = unary_union([f for f in faces if f.intersection(covered).area > TOL])
    leftover = material.difference(covered)

    parts = [
        g
        for g in getattr(leftover, "geoms", [leftover])
        if isinstance(g, Polygon) and g.area > TOL
    ]
    parts.sort(key=lambda g: (g.bounds[1], g.bounds[0]))

    junctions, issues = [], []
    for p in parts:
        x0, y0, x1, y1 = p.bounds
        touching = [wid for wid, r in rects.items() if r.distance(p) <= TOL]
        if min(x1 - x0, y1 - y0) <= thk_max + TOL and touching and not p.interiors:
            junctions.append(
                JunctionPiece(f"junction-{len(junctions) + 1:03d}", _ring(p), touching)
            )
        else:
            issues.append(
                Issue(
                    code="unexplained_region",
                    severity="warning",
                    message=f"region {x0:.1f},{y0:.1f}..{x1:.1f},{y1:.1f} enclosed by wall "
                    "lines but not a wall or junction; left empty",
                )
            )
    return junctions, issues
