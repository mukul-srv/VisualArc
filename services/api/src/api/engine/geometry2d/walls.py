"""Paired-line wall detection for orthogonal walls (MVP-0 convention).

Input: wall boundary segments in mm. Output: walls (centreline + thickness from
the distance between two parallel face lines), inferred junction pieces filling
L/T corners, and Issues. Never guesses: ambiguous pairings are blocking. Collinear
segments that overlap are the same line drawn twice: they are merged into one (the
union of the same points, nothing measured changes) and reported as a warning.
"""

import math
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from api.engine.canonical.model import Issue, Point2, SourceRef
from api.engine.settings import DEFAULTS, Settings


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
    sources: tuple[Segment, ...]  # 2 face segments; more after an opening merge

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


def wall_order(start: Point2, end: Point2) -> tuple[float, float, float, float]:
    """Wall id order: by start (y, x), then end (y, x)."""
    return (start[1], start[0], end[1], end[0])


def _axial(s: Segment, tol: float) -> _Axial | None:
    (x0, y0), (x1, y1) = s.start, s.end
    if abs(y1 - y0) <= tol:
        return _Axial(s, "h", (y0 + y1) / 2, min(x0, x1), max(x0, x1))
    if abs(x1 - x0) <= tol:
        return _Axial(s, "v", (x0 + x1) / 2, min(y0, y1), max(y0, y1))
    return None


def _usable(segments: list[Segment], tol: float) -> tuple[list[_Axial], list[Issue]]:
    axial, issues = [], []
    for s in segments:
        if math.dist(s.start, s.end) <= tol:
            issues.append(
                Issue(
                    code="degenerate_segment",
                    severity="warning",
                    message=f"zero-length wall segment {s.handle} ignored",
                    sources=[s.ref],
                )
            )
        elif (a := _axial(s, tol)) is None:
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


def _merge_overlaps(axial: list[_Axial], tol: float) -> tuple[list[_Axial], list[Issue]]:
    """Merge collinear segments (same axis, line and layer) that overlap into one covering their union.
    Segments that only touch end to end (split faces) stay as they are. Overlapping lines on different
    layers are not merged: the layer carries the wall role, so pair_walls blocks on them."""
    axial_pos = {a: n for n, a in enumerate(axial)}
    out, issues = [], []
    # lines within tol of each other are one line (float noise): number them, then order by layer and start
    line_id: dict[_Axial, int] = {}
    n, prev = -1, None
    for a in sorted(axial, key=lambda a: (a.axis, a.c)):
        if prev is None or a.axis != prev.axis or a.c - prev.c > tol:
            n, prev = n + 1, a
        line_id[a] = n
    by_line = sorted(axial, key=lambda a: (line_id[a], a.seg.layer, a.lo))
    i = 0
    while i < len(by_line):
        first = by_line[i]
        group, hi = [first], first.hi
        i += 1
        while (
            i < len(by_line)
            and by_line[i].axis == first.axis
            and by_line[i].seg.layer == first.seg.layer
            and abs(by_line[i].c - first.c) <= tol
            and by_line[i].lo < hi - tol
        ):
            group.append(by_line[i])
            hi = max(hi, by_line[i].hi)
            i += 1
        if len(group) == 1:
            out.append(first)
            continue
        rep = min(group, key=lambda a: axial_pos[a])  # the first drawn keeps its handle
        lo = min(a.lo for a in group)
        start, end = ((lo, first.c), (hi, first.c)) if first.axis == "h" else ((first.c, lo), (first.c, hi))
        merged = Segment(rep.seg.handle, rep.seg.layer, start, end)
        m = _Axial(merged, first.axis, first.c, lo, hi)
        axial_pos[m] = axial_pos[rep]
        out.append(m)
        handles = ", ".join(sorted(a.seg.handle for a in group))
        issues.append(
            Issue(
                code="overlapping_wall_lines",
                severity="warning",
                message=f"segments {handles} overlap on the same line; merged into one line "
                f"({lo:.1f} to {hi:.1f} mm, same extent, nothing moved)",
                sources=[a.seg.ref for a in group],
            )
        )
    out.sort(key=lambda a: axial_pos[a])
    return out, issues


def pair_walls(
    segments: list[Segment], settings: Settings = DEFAULTS
) -> tuple[list[PairedWall], list[Issue]]:
    tol = settings.tolerance_mm
    thk_min, thk_max = settings.wall_thickness_min_mm, settings.wall_thickness_max_mm
    axial, issues = _usable(segments, tol)
    axial, merged = _merge_overlaps(axial, tol)
    issues += merged

    cands: dict[_Axial, list[_Axial]] = {a: [] for a in axial}
    for i, a in enumerate(axial):
        for b in axial[i + 1 :]:
            if a.axis != b.axis:
                continue
            shared = min(a.hi, b.hi) - max(a.lo, b.lo)
            if shared <= tol:  # disjoint or touching end-to-end (split faces)
                continue
            if abs(a.c - b.c) <= tol:
                # same-layer overlaps were merged above, so this is the same line on two layers
                # (e.g. exterior vs interior role): the roles cannot both hold, never auto-resolved
                issues.append(
                    Issue(
                        code="overlapping_wall_lines",
                        severity="blocking",
                        message=f"segments {a.seg.handle} ({a.seg.layer}) and {b.seg.handle} "
                        f"({b.seg.layer}) overlap by {shared:.1f} mm on the same line but lie on "
                        "different layers; keep one",
                        sources=[a.seg.ref, b.seg.ref],
                    )
                )
                continue
            if not thk_min - tol <= abs(a.c - b.c) <= thk_max + tol:
                continue
            cands[a].append(b)
            cands[b].append(a)

    # One long face pairing with several split faces at the same offset is fine, and so are
    # partners at different offsets along different stretches (the wall changes thickness).
    # Partners at different offsets that compete for the same stretch (or sit on both sides of
    # it) mean we cannot tell which lines form the wall -> blocking, never a guess.
    ambiguous = set()
    for a in axial:
        offsets = [b.c - a.c for b in cands[a]]
        clash = {
            b
            for p, q in combinations(cands[a], 2)
            if abs(p.c - q.c) > tol and min(a.hi, p.hi, q.hi) - max(a.lo, p.lo, q.lo) > tol
            for b in (p, q)
        }
        if clash:
            ambiguous.add(a)
            issues.append(
                Issue(
                    code="ambiguous_pairing",
                    severity="blocking",
                    message=f"segment {a.seg.handle} has parallel partners at different "
                    f"offsets {sorted({round(b.c - a.c, 3) for b in clash})} mm over the same stretch",
                    sources=[a.seg.ref] + [b.seg.ref for b in cands[a] if b in clash],
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

    raw.sort(key=lambda r: wall_order(r[0], r[1]))
    walls = [PairedWall(f"wall-{n:03d}", *r) for n, r in enumerate(raw, 1)]
    return walls, issues


def _ring(p: Polygon) -> list[Point2]:
    """CCW exterior ring, collinear points dropped, starting at the min vertex."""
    pts = list(orient(p.simplify(0), 1.0).exterior.coords)[:-1]
    k = pts.index(min(pts))
    return pts[k:] + pts[:k]


def find_junctions(
    segments: list[Segment], walls: list[PairedWall], settings: Settings = DEFAULTS
) -> tuple[list[JunctionPiece], list[Issue]]:
    """Fill regions enclosed by wall lines that no wall rectangle covers.

    Faces of the noded wall-line arrangement that overlap a wall rectangle are wall
    material; material minus wall rectangles = corner/T gaps.
    """
    if not walls:
        return [], []
    tol, thk_max = settings.tolerance_mm, settings.wall_thickness_max_mm
    axial, _ = _usable(segments, tol)  # issues already reported by pair_walls
    rects = {w.id: w.rect() for w in walls}
    covered = unary_union(list(rects.values()))
    faces = polygonize(
        unary_union([LineString([a.seg.start, a.seg.end]) for a in axial])
    )
    material = unary_union([f for f in faces if f.intersection(covered).area > tol])
    leftover = material.difference(covered)

    parts = [
        g
        for g in getattr(leftover, "geoms", [leftover])
        if isinstance(g, Polygon) and g.area > tol
    ]
    parts.sort(key=lambda g: (g.bounds[1], g.bounds[0]))

    junctions, issues = [], []
    for p in parts:
        x0, y0, x1, y1 = p.bounds
        touching = [wid for wid, r in rects.items() if r.distance(p) <= tol]
        if min(x1 - x0, y1 - y0) <= thk_max + tol and touching and not p.interiors:
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
                    sources=[
                        s.ref for w in walls if w.id in touching for s in w.sources
                    ],
                )
            )
    return junctions, issues
