"""Openings (ADR-002 Option B, strict): door/window markers filling wall gaps.

Input: A-WALL segments and validated opening markers, in mm. Steps (ADR-002 §3-§6):
jamb lines coinciding with marker edges are removed before `pair_walls`; gaps
between consecutive collinear walls are found after pairing; each marker must fill
exactly one gap; walls joined only by validly marked gaps merge into one host wall.
Exact matching only (`tolerance_mm`, no snapping). Every mismatch is an Issue.
"""

import math
from dataclasses import dataclass, field

from shapely.geometry import Point, Polygon, box

from api.engine.canonical.model import (
    Issue,
    LineGeometry,
    Measured,
    Opening,
    OpeningDetail,
    Point2,
    SourceRef,
    Swing,
)
from api.engine.geometry2d.walls import (
    JunctionPiece,
    PairedWall,
    Segment,
    _axial,
    find_junctions,
    pair_walls,
    wall_order,
)
from api.engine.settings import DEFAULTS, Settings

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass(frozen=True)
class Marker:
    kind: str  # "door" | "window": the layer is the kind (ADR-002 §1)
    ref: SourceRef
    rect: Rect
    inferred: bool = False  # made from an unmarked gap (kind by rule), not drawn

    def edges(self, axis: str | None = None) -> list[tuple[Point2, Point2]]:
        """All 4 edges, or only those perpendicular to a host running along `axis`."""
        x0, y0, x1, y1 = self.rect
        across_h = [((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))]  # vertical edges
        across_v = [((x0, y0), (x1, y0)), ((x0, y1), (x1, y1))]  # horizontal edges
        if axis is None:
            return across_h + across_v
        return across_h if axis == "h" else across_v


def marker_rect(pts: list[Point2], tol: float) -> Rect | None:
    """Exactly 4 distinct vertices, edges alternately horizontal/vertical, else None."""
    if len(pts) != 4 or any(
        math.dist(a, b) <= tol for i, a in enumerate(pts) for b in pts[i + 1 :]
    ):
        return None
    axes = []
    for a, b in zip(pts, pts[1:] + pts[:1], strict=True):
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if dy <= tol < dx:
            axes.append("h")
        elif dx <= tol < dy:
            axes.append("v")
        else:
            return None
    if axes not in (["h", "v"] * 2, ["v", "h"] * 2):
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def on_marker_boundary(p: Point2, markers: list[Marker], tol: float) -> bool:
    return any(box(*m.rect).exterior.distance(Point(p)) <= tol for m in markers)


def _coincide(s: Segment, edge: tuple[Point2, Point2], tol: float) -> bool:
    a, b = edge
    return (math.dist(s.start, a) <= tol and math.dist(s.end, b) <= tol) or (
        math.dist(s.start, b) <= tol and math.dist(s.end, a) <= tol
    )


def _geom(w: PairedWall) -> tuple[str, float, float, float]:
    """(axis, centreline coordinate, lo, hi), same axis test as PairedWall.rect."""
    (x0, y0), (x1, y1) = w.start, w.end
    return ("h", y0, x0, x1) if y0 == y1 else ("v", x0, y0, y1)


def _box(axis: str, lo: float, hi: float, c0: float, c1: float) -> Polygon:
    return box(lo, c0, hi, c1) if axis == "h" else box(c0, lo, c1, hi)


def _refs(walls) -> list[SourceRef]:
    return [s.ref for w in walls for s in w.sources]


@dataclass(frozen=True, eq=False)
class _Gap:
    a: PairedWall  # lower-coordinate flanking wall
    b: PairedWall
    axis: str
    lo: float
    hi: float
    host_ok: bool  # equal centreline and thickness (ADR-002 §4.2)
    region: Polygon


def _touches(r: Polygon, other: Polygon, tol: float) -> bool:
    inter = r.intersection(other)
    return inter.area > tol or inter.length > tol


def _gaps(walls: list[PairedWall], tol: float) -> list[_Gap]:
    """Spaces between consecutive collinear walls (ADR-002 §4.2, §4.4).

    A space touched by any other wall rectangle (a perpendicular wall at a T or
    cross, or a wall in between) is junction/wall space, not a gap (§4.4).
    Collinear neighbours with different thickness/centreline are kept with
    host_ok=False so a marker there reports opening_host_mismatch.
    """
    rects = {id(w): w.rect() for w in walls}
    gaps = []
    for wa in walls:
        ax, ca, _, hi_a = _geom(wa)
        for wb in walls:
            bx, cb, lo_b, _ = _geom(wb)
            if bx != ax or wb is wa or lo_b - hi_a <= tol:
                continue
            ha, hb = wa.thickness / 2, wb.thickness / 2
            c0, c1 = max(ca - ha, cb - hb), min(ca + ha, cb + hb)
            if c1 - c0 <= tol:
                continue
            strip = _box(ax, hi_a, lo_b, c0, c1)
            if any(
                _touches(rects[id(w)], strip, tol)
                for w in walls
                if w is not wa and w is not wb
            ):
                continue
            host_ok = abs(ca - cb) <= tol and abs(wa.thickness - wb.thickness) <= tol
            region = (
                strip
                if host_ok
                else _box(ax, hi_a, lo_b, min(ca - ha, cb - hb), max(ca + ha, cb + hb))
            )
            gaps.append(_Gap(wa, wb, ax, hi_a, lo_b, host_ok, region))
    return gaps


def _caps(w: PairedWall) -> tuple[tuple[Point2, Point2], tuple[Point2, Point2]]:
    ax, c, lo, hi = _geom(w)
    h = w.thickness / 2
    if ax == "h":
        return ((lo, c - h), (lo, c + h)), ((hi, c - h), (hi, c + h))
    return ((c - h, lo), (c + h, lo)), ((c - h, hi), (c + h, hi))


def _plugs(walls: list[PairedWall], tol: float) -> list[Issue]:
    """gap_closed_by_jamb_pair: a wall whose two faces are the facing end caps of
    two flanking collinear equal walls (ADR-002 §6, probe 2)."""
    issues = []
    for p in walls:
        s1, s2 = p.sources[:2]
        for wa in walls:
            for wb in walls:
                if p is wa or p is wb or wa is wb:
                    continue
                (ax, ca, _, hi_a), (bx, cb, lo_b, _) = _geom(wa), _geom(wb)
                if (
                    ax != bx
                    or abs(ca - cb) > tol
                    or abs(wa.thickness - wb.thickness) > tol
                    or lo_b - hi_a <= tol
                ):
                    continue
                end_a, start_b = _caps(wa)[1], _caps(wb)[0]
                if (_coincide(s1, end_a, tol) and _coincide(s2, start_b, tol)) or (
                    _coincide(s2, end_a, tol) and _coincide(s1, start_b, tol)
                ):
                    issues.append(
                        Issue(
                            code="gap_closed_by_jamb_pair",
                            severity="blocking",
                            message=f"jamb lines {s1.handle} and {s2.handle} pair into "
                            f"a {p.thickness:g} mm wall closing the gap between "
                            f"{_geom(wa)[3]:g} and {_geom(wb)[2]:g}; ambiguous: solid "
                            "plug or opening. Mark an opening or remove the jambs",
                            sources=_refs([p, wa, wb]),
                        )
                    )
    return issues


@dataclass
class _Assoc:
    result: str  # multi | host | material | none | mismatch | match
    gaps: list[_Gap] = field(default_factory=list)
    deltas: list[float] = field(default_factory=list)


def _associate(m: Marker, gaps: list[_Gap], walls, tol: float) -> _Assoc:
    r = box(*m.rect)
    hits = [g for g in gaps if r.intersection(g.region).area > tol]
    if len(hits) >= 2:
        return _Assoc("multi", hits)
    if hits and not hits[0].host_ok:
        return _Assoc("host", hits)
    if any(r.intersection(w.rect()).area > tol for w in walls):
        return _Assoc("material", hits)
    if not hits:
        return _Assoc("none")
    deltas = [a - b for a, b in zip(m.rect, hits[0].region.bounds, strict=True)]
    if any(abs(d) > tol for d in deltas):
        return _Assoc("mismatch", hits, deltas)
    return _Assoc("match", hits)


@dataclass(frozen=True)
class FoundOpening:
    kind: str
    wall_id: str
    axis: str
    c: float  # host centreline coordinate
    lo: float
    hi: float
    offset: float
    marker: Marker
    jambs: tuple[Segment, ...]


@dataclass
class Resolution:
    walls: list[PairedWall]
    junctions: list[JunctionPiece]
    openings: list[FoundOpening]
    segments: list[Segment]  # the wall segments that went into pairing
    issues: list[Issue]
    unmarked: list = field(default_factory=list)  # gaps with no marker at all and nothing across them


def _analyse(segments, markers, consumed, settings):
    tol = settings.tolerance_mm
    pair_in = [s for i, s in enumerate(segments) if i not in consumed]
    walls, issues = pair_walls(pair_in, settings)
    gaps = _gaps(walls, tol)
    assoc = [_associate(m, gaps, walls, tol) for m in markers]
    confirmed = {
        i
        for i in consumed
        for m, a in zip(markers, assoc, strict=True)
        if a.result == "match"
        and any(_coincide(segments[i], e, tol) for e in m.edges(a.gaps[0].axis))
    }
    return pair_in, walls, issues, gaps, assoc, confirmed


def cut_walls_at_markers(
    segments: list[Segment], markers: list[Marker], settings: Settings = DEFAULTS
) -> tuple[list[Segment], list[Issue]]:
    """A marker lying exactly across a solid wall (its two edges along the wall are the wall's two
    face lines, which run on past both of its ends) cuts the wall there: each face line is split at the
    marker bounds, leaving the gap the marker then fills. Reported as a warning with the wall that was cut.
    A marker that only partly overlaps the wall, sits off the faces, or is at a wall end is left alone
    (the usual issues apply). Nothing else is changed."""
    tol, issues, segs = settings.tolerance_mm, [], list(segments)
    thk_min, thk_max = settings.wall_thickness_min_mm, settings.wall_thickness_max_mm
    for m in markers:
        x0, y0, x1, y1 = m.rect
        hits = []
        for axis, (c0, c1), (lo, hi) in (("h", (y0, y1), (x0, x1)), ("v", (x0, x1), (y0, y1))):
            if not thk_min - tol <= c1 - c0 <= thk_max + tol:
                continue
            faces = [
                [
                    i
                    for i, s in enumerate(segs)
                    if (a := _axial(s, tol))
                    and a.axis == axis
                    and abs(a.c - c) <= tol
                    and a.lo < lo - tol
                    and a.hi > hi + tol
                ]
                for c in (c0, c1)
            ]
            if all(len(f) == 1 for f in faces):
                hits.append((axis, lo, hi, [f[0] for f in faces]))
        if len(hits) != 1:  # none, or a square marker that could cut either way: not guessed
            continue
        axis, lo, hi, idx = hits[0]
        cut = []
        for i in idx:
            s, a = segs[i], _axial(segs[i], tol)
            pieces = [(a.lo, lo), (hi, a.hi)]
            cut.append((i, [
                Segment(s.handle, s.layer, (p, a.c) if axis == "h" else (a.c, p),
                        (q, a.c) if axis == "h" else (a.c, q))
                for p, q in pieces
            ]))
        faces_cut = [segs[i] for i in idx]
        for i, pieces in sorted(cut, reverse=True):
            segs[i : i + 1] = pieces
        issues.append(
            Issue(
                code="opening_cut_into_wall",
                severity="warning",
                message=f"{m.kind} marker {m.ref.entity_handle} lies across solid wall "
                f"(faces {faces_cut[0].handle}, {faces_cut[1].handle}); the wall was cut at the "
                "marker bounds and the opening made from it",
                sources=[m.ref, *(s.ref for s in faces_cut)],
            )
        )
    return segs, issues


def resolve_openings(
    segments: list[Segment],
    markers: list[Marker],
    settings: Settings = DEFAULTS,
    door_hints: tuple[Point2, ...] = (),
) -> Resolution:
    """`_resolve`, then each unmarked gap of a plausible width becomes an opening and the walls are resolved
    again with it. Kind: a door when a door-swing arc is centred at the gap (`door_hints`: arc centres, mm),
    otherwise a window (default sill), and the report says which and why. Gaps outside the width range stay
    unmarked gaps; nothing is bridged that has a face line across it or differing walls either side."""
    res = _resolve(segments, markers, settings)
    lo_w, hi_w = settings.bridged_opening_width_mm
    todo = [g for g in res.unmarked if lo_w <= g.hi - g.lo <= hi_w] if settings.bridge_unmarked_gaps else []
    if not todo:
        return res
    new, why = [], {}
    for g in todo:
        c, t = _geom(g.a)[1], g.a.thickness
        rect = (g.lo, c - t / 2, g.hi, c + t / 2) if g.axis == "h" else (c - t / 2, g.lo, c + t / 2, g.hi)
        swing = next((p for p in door_hints if box(*rect).buffer(t / 2).covers(Point(p))), None)
        kind = "door" if swing else "window"
        m = Marker(kind, g.a.sources[0].ref, rect, inferred=True)
        new.append(m)
        why[id(m)] = (
            f"a door-swing arc is centred at ({swing[0]:g}, {swing[1]:g})" if swing
            else "no door-swing arc at the gap, so assumed a window (default sill)"
        )
    res = _resolve(segments, [*markers, *new], settings)
    for m in new:
        o = next((o for o in res.openings if o.marker is m), None)
        if o is None:
            continue  # did not resolve to an exact gap: the usual issues for it are in the result
        res.issues.append(
            Issue(
                code="unmarked_gap_bridged",
                severity="warning",
                message=f"unmarked gap {o.lo:g}..{o.hi:g} ({o.hi - o.lo:g} mm) on {o.wall_id} bridged as a "
                f"{m.kind} opening (inferred, not drawn): {why[id(m)]}. Mark it on the door or window "
                "layer to say otherwise",
                sources=[m.ref, *(j.ref for j in o.jambs)],
            )
        )
    return res


def _resolve(
    segments: list[Segment], markers: list[Marker], settings: Settings = DEFAULTS
) -> Resolution:
    tol = settings.tolerance_mm
    # §3: consume segments on any marker edge, then keep only the jambs of markers
    # that exactly fill a gap (edges perpendicular to the host). Shrinks to a fixpoint.
    consumed = {
        i
        for i, s in enumerate(segments)
        for m in markers
        if any(_coincide(s, e, tol) for e in m.edges())
    }
    while True:
        pair_in, walls, issues, gaps, assoc, confirmed = _analyse(
            segments, markers, consumed, settings
        )
        if confirmed == consumed:
            break
        consumed = confirmed

    issues += _plugs(walls, tol)
    on_gap: dict[int, list[int]] = {}  # id(gap) -> marker indices overlapping it
    for k, a in enumerate(assoc):
        for g in a.gaps:
            on_gap.setdefault(id(g), []).append(k)

    unmarked: list[_Gap] = []
    valid: dict[int, int] = {}  # id(gap) -> its single exact marker
    for g in gaps:
        if not g.host_ok:
            continue
        ks = on_gap.get(id(g), [])
        mrefs = [markers[k].ref for k in ks]
        c, t = _geom(g.a)[1], g.a.thickness
        faces = [
            s
            for s in pair_in
            if (a := _axial(s, tol))
            and a.axis == g.axis
            and min(abs(a.c - c + t / 2), abs(a.c - c - t / 2)) <= tol
            and min(a.hi, g.hi) - max(a.lo, g.lo) > tol
        ]
        where = f"{g.lo:g}..{g.hi:g} on {_geom(g.a)[0]}-wall at {c:g}"
        if faces:
            issues.append(
                Issue(
                    code="partial_wall_gap",
                    severity="blocking",
                    message=f"gap {where}: face line(s) "
                    f"{', '.join(s.handle for s in faces)} continue across it while "
                    "the other face is broken; break both faces or neither",
                    sources=mrefs + _refs([g.a, g.b]) + [s.ref for s in faces],
                )
            )
        if not ks:
            if not faces and g.host_ok:
                unmarked.append(g)
            issues.append(
                Issue(
                    code="unmarked_wall_gap",
                    severity="warning",
                    message=f"gap {where} ({g.hi - g.lo:g} mm) has no opening marker; "
                    "left as a full-height void, walls not merged",
                    sources=_refs([g.a, g.b]),
                )
            )
        elif len(ks) >= 2:
            issues.append(
                Issue(
                    code="multiple_opening_markers",
                    severity="blocking",
                    message=f"gap {where} has {len(ks)} opening markers "
                    f"({', '.join(r.entity_handle for r in mrefs)}); one gap = one "
                    "opening",
                    sources=mrefs + _refs([g.a, g.b]),
                )
            )
        elif assoc[ks[0]].result == "match" and not faces:
            valid[id(g)] = ks[0]

    # §4.5 merge: walls joined only by valid marked gaps become one host wall
    nxt = {id(g.a): g.b for g in gaps if id(g) in valid}
    has_prev = {id(g.b) for g in gaps if id(g) in valid}
    merged, host_of = [], {}
    for w in walls:
        if id(w) in has_prev:
            continue
        chain = [w]
        while id(chain[-1]) in nxt:
            chain.append(nxt[id(chain[-1])])
        end = chain[-1].end
        # one line: the end takes the start's constant coordinate (walls on a line can differ by float noise,
        # and a wall whose ends differ at all would be read as running the other way)
        end = (end[0], chain[0].start[1]) if _geom(chain[0])[0] == "h" else (chain[0].start[0], end[1])
        m = PairedWall(
            "", chain[0].start, end, w.thickness,
            tuple(s for c in chain for s in c.sources),
        )  # fmt: skip
        merged.append(m)
        host_of.update({id(c): m for c in chain})
    merged.sort(key=lambda w: wall_order(w.start, w.end))
    final = {
        id(m): PairedWall(f"wall-{n:03d}", m.start, m.end, m.thickness, m.sources)
        for n, m in enumerate(merged, 1)
    }
    out_walls = [final[id(m)] for m in merged]

    found, closures = [], []
    for g in gaps:
        if id(g) not in valid:
            continue
        m = markers[valid[id(g)]]
        host = final[id(host_of[id(g.a)])]
        ax, c, lo, _ = _geom(host)
        jambs = tuple(
            segments[i]
            for i in sorted(consumed)
            if any(_coincide(segments[i], e, tol) for e in m.edges(ax))
        )
        found.append(
            FoundOpening(m.kind, host.id, ax, c, g.lo, g.hi, g.lo - lo, m, jambs)
        )
        # the marker's edges on the face lines close the wall-line loops for junctions
        closures += [
            Segment(m.ref.entity_handle, m.ref.layer, a, b)
            for a, b in m.edges("v" if ax == "h" else "h")
        ]

    junctions, junction_issues = find_junctions(pair_in + closures, out_walls, settings)
    jpolys = [Polygon(j.polygon) for j in junctions]

    for m, a in zip(markers, assoc, strict=True):
        name = f"{m.kind} marker {m.ref.entity_handle}"
        gwalls = [w for g in a.gaps for w in (g.a, g.b)]
        if a.result == "multi":
            issues.append(
                Issue(
                    code="opening_spans_multiple_gaps",
                    severity="blocking",
                    message=f"{name} overlaps {len(a.gaps)} wall gaps; one marker "
                    "must fill exactly one gap",
                    sources=[m.ref] + _refs(gwalls),
                )
            )
        elif a.result == "host":
            g = a.gaps[0]
            issues.append(
                Issue(
                    code="opening_host_mismatch",
                    severity="blocking",
                    message=f"{name} sits between collinear walls that differ in "
                    f"thickness ({g.a.thickness:g} vs {g.b.thickness:g} mm) or "
                    f"centreline ({_geom(g.a)[1]:g} vs {_geom(g.b)[1]:g})",
                    sources=[m.ref] + _refs(gwalls),
                )
            )
        elif a.result == "material" or (
            a.result == "none"
            and any(box(*m.rect).intersection(p).area > tol for p in jpolys)
        ):
            issues.append(
                Issue(
                    code="opening_marker_without_gap",
                    severity="blocking",
                    message=f"{name} overlaps wall or junction material; break the "
                    "wall lines so the marker exactly fills a gap",
                    sources=[m.ref],
                )
            )
        elif a.result == "none":
            issues.append(
                Issue(
                    code="opening_marker_outside_wall",
                    severity="blocking",
                    message=f"{name} overlaps no wall or wall gap",
                    sources=[m.ref],
                )
            )
        elif a.result == "mismatch":
            d = ", ".join(
                f"{k} {v:+g} mm"
                for k, v in zip(("x0", "y0", "x1", "y1"), a.deltas, strict=True)
            )
            issues.append(
                Issue(
                    code="opening_marker_mismatch",
                    severity="blocking",
                    message=f"{name} does not exactly fill its wall gap "
                    f"(marker - gap: {d}); no snapping",
                    sources=[m.ref] + _refs(gwalls),
                )
            )
    return Resolution(out_walls, junctions, found, pair_in, issues + junction_issues, unmarked)


def build_openings(
    found: list[FoundOpening],
    wall_height: float | None,
    heights: dict[str, tuple[float | None, float | None]],
    from_user: bool,
    settings: Settings = DEFAULTS,
) -> tuple[list[Opening], list[Issue]]:
    """Canonical Openings with ADR-002 §5/§7 provenance.

    `heights`: kind -> (height flag, sill flag); None = use the Settings default.
    Door sill has no flag (always defaulted).
    """
    s, cap = settings, settings.unmapped_ref_cap
    defaults = {
        "door": (s.default_door_height_mm, s.default_door_sill_mm),
        "window": (s.default_window_height_mm, s.default_window_sill_mm),
    }
    measured_default = "user_provided" if from_user else "source_extracted"
    # span start (y, x): the opening id order, also used for issue refs
    found = sorted(found, key=lambda o: (o.c, o.lo) if o.axis == "h" else (o.lo, o.c))
    openings, issues = [], []
    for kind in ("door", "window"):
        mine = [o for o in found if o.kind == kind]
        given = heights.get(kind, (None, None))
        (h, h_src), (sill, sill_src) = (
            (v, "user_provided") if v is not None else (d, "defaulted")
            for v, d in zip(given, defaults[kind], strict=True)
        )
        dflt = [
            f"{name} {v:g} mm"
            for name, v, src in (("height", h, h_src), ("sill", sill, sill_src))
            if src == "defaulted"
        ]
        if mine and dflt:
            more = f"; first {cap} of {len(mine)} listed" if len(mine) > cap else ""
            issues.append(
                Issue(
                    code="opening_dimension_defaulted",
                    severity="warning",
                    message=f"{len(mine)} {kind} opening(s): {', '.join(dflt)} from "
                    f"provisional Settings defaults (not in the DXF){more}",
                    sources=[o.marker.ref for o in mine[:cap]],
                )
            )
        for o in mine:
            if wall_height is not None and sill + h > wall_height + s.tolerance_mm:
                issues.append(
                    Issue(
                        code="opening_exceeds_wall_height",
                        severity="blocking",
                        message=f"{kind} marker {o.marker.ref.entity_handle}: sill "
                        f"{sill:g} + height {h:g} = {sill + h:g} mm exceeds wall "
                        f"height {wall_height:g} mm; opening omitted",
                        sources=[o.marker.ref] + [j.ref for j in o.jambs],
                    )
                )
                continue
            ends = (
                ((o.lo, o.c), (o.hi, o.c))
                if o.axis == "h"
                else ((o.c, o.lo), (o.c, o.hi))
            )
            openings.append((o, ends, h, h_src, sill, sill_src))
    openings.sort(key=lambda t: (t[1][0][1], t[1][0][0]))
    details = [_detail(o, h, sill, s) for o, _, h, _, sill, _ in openings]
    bare = [t[0] for t, d in zip(openings, details, strict=True) if d is None]
    if bare:
        issues.append(
            Issue(
                code="opening_detail_skipped",
                severity="warning",
                message=f"{len(bare)} opening(s) too small for a {s.opening_frame_width_mm:g} mm "
                f"frame around a panel; modelled as a plain hole, no frame or leaf/glass: "
                + ", ".join(o.marker.ref.entity_handle for o in bare[:cap]),
                sources=[o.marker.ref for o in bare[:cap]],
            )
        )
    return [
        Opening(
            id=f"opening-{n:03d}",
            kind=o.kind,
            wall_id=o.wall_id,
            span=LineGeometry(start=ends[0], end=ends[1]),
            offset=Measured(value=o.offset, source="inferred" if o.marker.inferred else measured_default),
            width=Measured(value=o.hi - o.lo, source="inferred" if o.marker.inferred else measured_default),
            height=Measured(value=h, source=h_src),
            sill_height=Measured(value=sill, source=sill_src),
            sources=[o.marker.ref] + [j.ref for j in o.jambs],
            detail=d,
        )
        for n, ((o, ends, h, h_src, sill, sill_src), d) in enumerate(zip(openings, details, strict=True), 1)
    ], issues


def _detail(o: FoundOpening, height: float, sill: float, s: Settings) -> OpeningDetail | None:
    """Frame + panel sizes; None when the frame leaves no room for the panel (no guessing)."""
    fw = s.opening_frame_width_mm
    if o.hi - o.lo <= 2 * fw or height <= (fw if o.kind == "door" else 2 * fw):
        return None
    door = o.kind == "door"
    return OpeningDetail(
        frame_width=Measured(value=fw, source="defaulted"),
        panel="leaf" if door else "glass",
        panel_thickness=Measured(
            value=s.door_leaf_thickness_mm if door else s.window_glass_thickness_mm,
            source="defaulted",
        ),
    )


@dataclass(frozen=True)
class SwingArc:
    centre: Point2
    mid: Point2  # a point on the arc halfway along its sweep
    ref: SourceRef


def door_swings(
    found: list[FoundOpening], arcs: list[SwingArc], settings: Settings = DEFAULTS
) -> tuple[dict[str, Swing], list[Issue]]:
    """Swing per door marker handle from the door-layer arc centred on one of its corners
    (the hinge). A door with no such arc, or with several, gets no swing and an issue."""
    tol, cap = settings.tolerance_mm, settings.unmapped_ref_cap
    out: dict[str, Swing] = {}
    missing, clashes = [], []
    for o in (f for f in found if f.kind == "door"):
        x0, y0, x1, y1 = o.marker.rect
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        mine = [a for a in arcs if any(math.dist(a.centre, c) <= tol for c in corners)]
        if len(mine) != 1:
            (clashes if mine else missing).append(o)
            continue
        a, i = mine[0], 0 if o.axis == "h" else 1
        hinge_at = a.centre[i]
        if abs(hinge_at - o.lo) > tol and abs(hinge_at - o.hi) > tol:
            missing.append(o)  # centred on a corner but not at a span end: not read
            continue
        n = 1 - i  # axis across the wall
        side = "+" if a.mid[n] > o.c else "-"
        out[o.marker.ref.entity_handle] = Swing(
            hinge="start" if abs(hinge_at - o.lo) <= tol else "end",
            opens_toward=f"{side}{'xy'[n]}",
            source=a.ref,
        )
    issues = []
    for code, severity, group, why in (
        ("door_swing_not_found", "warning", missing,
         "no swing arc on the door layer centred on a marker corner; swing and hinge left unset"),
        ("door_swing_ambiguous", "warning", clashes,
         "several swing arcs centred on its corners; swing and hinge left unset"),
    ):
        if group:
            more = f"; first {cap} of {len(group)} listed" if len(group) > cap else ""
            issues.append(Issue(
                code=code, severity=severity,
                message=f"{len(group)} door(s): {why}{more}",
                sources=[g.marker.ref for g in group[:cap]],
            ))
    return out, issues
