"""Paired-line wall detection for orthogonal walls (MVP-0 convention).

Input: wall boundary segments in mm. Output: walls (centreline + thickness from
the distance between two parallel face lines), inferred junction pieces filling
L/T corners, and Issues. Never guesses: ambiguous pairings are blocking. Collinear
segments that overlap are the same line drawn twice: they are merged into one (the
union of the same points, nothing measured changes) and reported as a warning.
"""

import math
from dataclasses import dataclass, replace
from itertools import combinations

from shapely import set_precision
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from api.engine.canonical.model import Issue, Point2, SourceRef, Suggestion
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
        if x0 == x1:  # vertical
            return box(x0 - h, y0, x0 + h, y1)
        nx, ny = normal(self.start, self.end)  # diagonal: the same footprint turned to its direction
        return Polygon([(x0 - nx * h, y0 - ny * h), (x1 - nx * h, y1 - ny * h),
                        (x1 + nx * h, y1 + ny * h), (x0 + nx * h, y0 + ny * h)])


@dataclass(frozen=True)
class JunctionPiece:
    id: str
    polygon: list[Point2]
    wall_ids: list[str]


def normal(a: Point2, b: Point2) -> Point2:
    """Unit normal of the line a->b (left of its direction); exactly (0, 1) / (-1, 0) on the axes."""
    d = math.dist(a, b)
    return (-(b[1] - a[1]) / d, (b[0] - a[0]) / d)


def rotate(p: Point2, angle: float) -> Point2:
    c, s = math.cos(angle), math.sin(angle)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def skewed_groups(segments: list[Segment], settings: Settings) -> tuple[list[Segment], list[tuple[float, list[Segment]]]]:
    """Split off the wall lines that are neither horizontal nor vertical (within tolerance_mm) and group them
    by direction: [(angle in radians, [segments])]. Angles are taken mod 180 deg; a group's angle is that of
    its longest line. Zero-length lines stay with the rest (pair_walls reports them)."""
    tol, near = settings.tolerance_mm, math.radians(settings.diagonal_angle_tol_deg)
    ortho, skew = [], []

    def off_axis(s: Segment) -> float:  # angle to the nearest axis: a drafting slip, not a diagonal, when tiny
        a = abs(math.atan2(s.end[1] - s.start[1], s.end[0] - s.start[0])) % (math.pi / 2)
        return min(a, math.pi / 2 - a)

    for s in segments:
        if (math.dist(s.start, s.end) <= tol or _axial(s, tol) is not None or not settings.diagonal_walls
                or off_axis(s) <= near):
            ortho.append(s)
        else:
            skew.append(s)

    def theta(s: Segment) -> float:
        t = math.atan2(s.end[1] - s.start[1], s.end[0] - s.start[0]) % math.pi
        return t - math.pi if t > math.pi - math.radians(settings.diagonal_angle_tol_deg) else t

    groups: list[list[Segment]] = []
    for s in sorted(skew, key=theta):
        if groups and theta(s) - theta(groups[-1][-1]) <= math.radians(settings.diagonal_angle_tol_deg):
            groups[-1].append(s)
        else:
            groups.append([s])
    return ortho, [(theta(max(g, key=lambda s: math.dist(s.start, s.end))), g) for g in groups]


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


def heal_gaps(segments: list[Segment], markers=(), settings: Settings = DEFAULTS) -> tuple[list[Segment], list[Issue]]:
    """Close small gaps between collinear wall lines of one layer (drafting slips, not openings): the two
    lines are joined into one over the gap. Only gaps up to settings.heal_gap_max_mm, never one an opening
    marker touches; wider gaps are left for the normal gap/opening rules. Every heal is reported with its
    size and both lines (the joined line keeps the first line's handle)."""
    if not settings.heal_wall_gaps:
        return segments, []
    tol, issues = settings.tolerance_mm, []
    axial = {id(s): _axial(s, tol) for s in segments}
    order = sorted((s for s in segments if axial[id(s)] and math.dist(s.start, s.end) > tol),
                   key=lambda s: (axial[id(s)].axis, round(axial[id(s)].c / max(tol, 1e-3)), s.layer, axial[id(s)].lo))
    out: dict[int, Segment | None] = {}
    cur: Segment | None = None
    origin: Segment | None = None  # the drawn line a chain of joins started from
    for s in order:
        a = axial[id(s)]
        if cur is not None:
            c = axial[id(cur)]
            gap = a.lo - c.hi
            same = (c.axis, c.seg.layer) == (a.axis, s.layer) and abs(c.c - a.c) <= tol
            near = tol < gap <= settings.heal_gap_max_mm and gap < settings.wall_thickness_min_mm
            if same and near and not _marker_in_gap(markers, a.axis, c.c, c.hi, a.lo, tol):
                lo, hi = c.lo, max(c.hi, a.hi)
                start, end = ((lo, c.c), (hi, c.c)) if a.axis == "h" else ((c.c, lo), (c.c, hi))
                joined = Segment(cur.handle, cur.layer, start, end)
                axial[id(joined)] = _Axial(joined, a.axis, c.c, lo, hi)
                out[id(s)] = None
                out[id(origin)] = joined
                issues.append(Issue(
                    code="wall_gap_healed", severity="warning",
                    message=f"gap of {gap:.1f} mm between wall lines {cur.handle} and {s.handle} on {s.layer} "
                    f"closed (limit {settings.heal_gap_max_mm:g} mm); the lines were joined, nothing else moved",
                    sources=[cur.ref, s.ref],
                    suggestions=[Suggestion(kind="gap_close", value=f"{gap:g}", label=f"close the {gap:.1f} mm gap in the drawing")],
                ))
                cur = joined
                continue
        cur = origin = s
    if not issues:
        return segments, []
    res: list[Segment] = []
    for s in segments:
        r = out.get(id(s), s)
        if r is not None:
            res.append(r)
    return res, issues


def _marker_in_gap(markers, axis: str, c: float, lo: float, hi: float, tol: float) -> bool:
    for m in markers:
        x0, y0, x1, y1 = m.rect
        along, across = ((x0, x1), (y0, y1)) if axis == "h" else ((y0, y1), (x0, x1))
        if along[0] < hi + tol and along[1] > lo - tol and across[0] - tol <= c <= across[1] + tol:
            return True
    return False


def _is_end_cap(a: _Axial, w: "PairedWall", tol: float) -> bool:
    """`a` is a line across the end of wall `w`: perpendicular to it, at its start or end, spanning exactly
    its thickness."""
    (x0, y0), (x1, y1) = w.start, w.end
    h = w.thickness / 2
    if y0 == y1:  # horizontal wall: a cap is a vertical line at an end
        c, ends = y0, sorted((x0, x1))
        return a.axis == "v" and any(abs(a.c - e) <= tol for e in ends) and abs(a.lo - (c - h)) <= tol and abs(a.hi - (c + h)) <= tol
    c, ends = x0, sorted((y0, y1))
    return a.axis == "h" and any(abs(a.c - e) <= tol for e in ends) and abs(a.lo - (c - h)) <= tol and abs(a.hi - (c + h)) <= tol


def _shared(a: _Axial, b: _Axial) -> float:
    return min(a.hi, b.hi) - max(a.lo, b.lo)


def _clash(a: _Axial, partners: list[_Axial], tol: float) -> set[_Axial]:
    """Partners at different offsets that compete for the same stretch of `a`."""
    return {
        b
        for p, q in combinations(partners, 2)
        if abs(p.c - q.c) > tol and min(a.hi, p.hi, q.hi) - max(a.lo, p.lo, q.lo) > tol
        for b in (p, q)
    }


def _describe(a: _Axial, b: _Axial, tol: float) -> str:
    return f"{b.seg.handle} (offset {b.c - a.c:g} mm, {_shared(a, b):g} mm shared)"


def _dominant(
    a: _Axial, clash: set[_Axial], ratio: float, tol: float, thickness: tuple[float, float]
) -> tuple[list[_Axial], list[_Axial]] | None:
    """(kept partners, rejected partners) when one offset's partners share far more of `a` than
    every other offset's (each at most `ratio` of it); None when no rule picks one."""
    groups: dict[float, list[_Axial]] = {}
    for b in sorted(clash, key=lambda b: (b.c, b.lo)):
        key = next((k for k in groups if abs(k - b.c) <= tol), b.c)
        groups.setdefault(key, []).append(b)
    total = {k: sum(_shared(a, b) for b in g) for k, g in groups.items()}
    best = max(total, key=total.get)
    others = [k for k in groups if k != best]
    if any(total[k] > ratio * total[best] for k in others):
        # no offset dominates `a`: but if its competing partners are themselves a wall (a distance within
        # the wall thickness range, so they pair with each other) over a far longer stretch, `a` is a
        # stray line beside that wall and pairs with none (reported). Partners too far apart to be a
        # wall prove nothing about `a`: that stays blocking.
        if all(
            thickness[0] - tol <= abs(p.c - q.c) <= thickness[1] + tol
            and _shared(p, q) * ratio >= max(_shared(a, p), _shared(a, q))
            for p, q in combinations(clash, 2)
            if abs(p.c - q.c) > tol
        ):
            return [], sorted(clash, key=lambda b: (b.c, b.lo))
        return None
    return groups[best], [b for k in others for b in groups[k]]


def pair_walls(
    segments: list[Segment], settings: Settings = DEFAULTS
) -> tuple[list[PairedWall], list[Issue]]:
    tol = settings.tolerance_mm
    thk_min, thk_max = settings.wall_thickness_min_mm, settings.wall_thickness_max_mm
    segments, groups = skewed_groups(segments, settings)
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
    # it) mean we cannot tell which lines form the wall -> blocking, unless one distance clearly
    # dominates (see _dominant): then that pairing is kept, the others are rejected, and a warning
    # lists both. No rule picking one stays blocking, never a guess.
    ambiguous = set()
    unpaired: list[_Axial] = []
    for a in axial:
        clash = _clash(a, cands[a], tol)
        if clash and (pick := _dominant(a, clash, settings.partner_dominance_ratio, tol, (thk_min, thk_max))):
            keep, rejected = pick
            for b in rejected:
                cands[a].remove(b)
                cands[b].remove(a)
            how = (
                f"paired with {', '.join(_describe(a, b, tol) for b in keep)}"
                if keep
                else "left unpaired (its partners already form walls with each other over a far longer stretch)"
            )
            issues.append(
                Issue(
                    code="ambiguous_pairing_resolved",
                    severity="warning",
                    message=f"segment {a.seg.handle} had partners at different distances over the same "
                    f"stretch; {how}; rejected {', '.join(_describe(a, b, tol) for b in rejected)} "
                    f"(each shares at most {settings.partner_dominance_ratio:.0%} of the other stretch: "
                    "a corner or stub, not a second wall)",
                    sources=[a.seg.ref, *(b.seg.ref for b in keep), *(b.seg.ref for b in rejected)],
                )
            )
            clash = _clash(a, cands[a], tol)
        offsets = [b.c - a.c for b in cands[a]]
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
            unpaired.append(a)

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

    raw, box_issues = _one_wall_per_box(raw, tol)
    issues += box_issues
    raw.sort(key=lambda r: wall_order(r[0], r[1]))
    walls = [PairedWall(f"wall-{n:03d}", *r) for n, r in enumerate(raw, 1)]
    if groups:  # each direction group is paired in its own frame (its lines horizontal), then turned back
        local = replace(settings, tolerance_mm=settings.diagonal_tol_mm, diagonal_walls=False)
        found = []
        for angle, segs in groups:
            turn = lambda sg, a: Segment(sg.handle, sg.layer, rotate(sg.start, a), rotate(sg.end, a))
            ws, iss = pair_walls([turn(sg, -angle) for sg in segs], local)
            issues += iss
            found += [PairedWall("", rotate(w.start, angle), rotate(w.end, angle), w.thickness,
                                 tuple(turn(sg, angle) for sg in w.sources)) for w in ws]
        walls += found
        walls = [replace(w, id=f"wall-{n:03d}") for n, w in enumerate(walls, 1)]
    caps = [a for a in unpaired if any(_is_end_cap(a, w, tol) for w in walls)]
    for a in unpaired:
        if a not in caps:
            issues.append(
                Issue(
                    code="unpaired_segment",
                    severity="warning",
                    message=f"segment {a.seg.handle} has no parallel partner "
                    f"within {thk_min}-{thk_max} mm",
                    sources=[a.seg.ref],
                )
            )
    if caps:
        cap = settings.unmapped_ref_cap
        issues.append(
            Issue(
                code="wall_end_caps_consumed",
                severity="warning",
                message=f"{len(caps)} loose line(s) close the end of a wall across its full thickness and "
                "were taken as that wall's end cap, not as unpaired wall lines: "
                + ", ".join(a.seg.handle for a in caps[:cap]) + ("; ..." if len(caps) > cap else ""),
                sources=[a.seg.ref for a in caps[:cap]],
            )
        )
    return walls, issues


def _one_wall_per_box(raw: list, tol: float) -> tuple[list, list[Issue]]:
    """Two pairings of the same material: a pair of lines further apart than they are long (the end caps of
    something, a wall drawn as a closed box, the jamb lines of a short stub) next to real walls (pairs at least
    as long as they are thick). A wall is longer than it is thick, so a cross pair whose material the real
    walls already cover is dropped and reported (its lines are their end caps). One that covers material
    nothing else does stays a wall (a pier drawn only by its two short sides) with a warning. Identical
    footprints are kept once."""
    rects = [PairedWall("-", *r).rect() for r in raw]
    cross = [math.dist(r[0], r[1]) < r[2] - tol for r in raw]
    drop, issues = set(), []

    def same(i: int, j: int) -> bool:
        return rects[i].buffer(tol).covers(rects[j]) and rects[j].buffer(tol).covers(rects[i])

    def note(code: str, i: int, others: list[int], why: str) -> Issue:
        r = raw[i]
        return Issue(
            code=code,
            severity="warning",
            message=f"lines {r[3][0].handle} and {r[3][1].handle} are {r[2]:g} mm apart but only "
            f"{math.dist(r[0], r[1]):g} mm long: {why}",
            sources=[s.ref for k in (i, *others) for s in raw[k][3]],
        )

    for i in range(len(raw)):  # equal footprints of real walls (a square box): the first stays
        if not cross[i] and any(j < i and not cross[j] and j not in drop and same(i, j) for j in range(i)):
            drop.add(i)
            twin = next(j for j in range(i) if not cross[j] and j not in drop and same(i, j))
            issues.append(note("short_cross_pair_ignored", i, [twin], "the same footprint as another pair, kept once"))
    real = [i for i in range(len(raw)) if not cross[i] and i not in drop]
    covered = unary_union([rects[i] for i in real]).buffer(tol) if real else Polygon()
    for i in range(len(raw)):
        if not cross[i]:
            continue
        under = [j for j in real if rects[j].intersects(rects[i]) and rects[j].intersection(rects[i]).area > tol]
        twin = next((j for j in range(i) if cross[j] and j not in drop and same(i, j)), None)
        left = rects[i].difference(covered)  # what no wall covers: nothing, or at most one corner square of
        # the walls' own thickness (the cross pair's length), which junction detection fills
        gap = left.is_empty or max(left.bounds[2] - left.bounds[0], left.bounds[3] - left.bounds[1]) <= math.dist(raw[i][0], raw[i][1]) + tol
        if gap and rects[i].area - left.area > tol:
            drop.add(i)
            issues.append(note("short_cross_pair_ignored", i, under, "its material is covered by walls "
                               "that are longer than thick: read as their end caps, not a second wall; not built"))
        elif twin is not None:
            drop.add(i)
            issues.append(note("short_cross_pair_ignored", i, [twin], "the same footprint as another pair, kept once"))
        else:
            issues.append(note("short_cross_pair_unexplained", i, under, "no wall covers this material, so "
                               "it is built as a wall (a pier drawn by its two short sides?); check it"))
    return [r for i, r in enumerate(raw) if i not in drop], issues


def _min_side(p: Polygon) -> float:
    """Shorter side of the bounding box; for a piece with a slanted edge, of its minimum rotated rectangle
    when that is smaller (a corner wedge between a diagonal and another wall)."""
    x0, y0, x1, y1 = p.bounds
    side = min(x1 - x0, y1 - y0)
    if all(a[0] == b[0] or a[1] == b[1] for a, b in zip(p.exterior.coords, p.exterior.coords[1:])):
        return side
    r = list(p.minimum_rotated_rectangle.exterior.coords)
    return min(side, math.dist(r[0], r[1]), math.dist(r[1], r[2]))


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
    lines = [s for s in segments if math.dist(s.start, s.end) > tol]  # degenerate ones are reported by pair_walls
    rects = {w.id: w.rect() for w in walls}
    covered = unary_union(list(rects.values()))
    diagonal = any(w.start[0] != w.end[0] and w.start[1] != w.end[1] for w in walls)
    net = [LineString([s.start, s.end]) for s in lines]
    if diagonal:  # turned lines meet to float noise only: put the nodes on a thousandth-of-a-mm grid
        net = [set_precision(g, tol * 1000) for g in net]
    faces = polygonize(unary_union(net))
    material = unary_union([f for f in faces if f.intersection(covered).area > tol])
    leftover = material.difference(covered)
    if diagonal:
        # a diagonal wall's footprint matches its face lines only to float noise: the hairline slivers along
        # it would join separate corner pieces, so thin strips (a thousandth of a mm) are opened away
        eps = tol * 1000
        leftover = leftover.buffer(-eps, join_style="mitre").buffer(eps, join_style="mitre")

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
        if _min_side(p) <= thk_max + tol and touching and not p.interiors:
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
