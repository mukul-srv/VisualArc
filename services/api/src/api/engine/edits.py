"""User edits of one floor (Section D): move/resize/add/remove walls and openings, rename rooms.

Ids are positional (`wall-003`, renumbered on any change), so an edit never names an id: it carries a
snapshot of its target (`WallRef` / `OpeningRef`: geometry plus the source handles the model gave it).
Edits run at the reader's segment/marker level, before openings are resolved, so junctions, rooms,
roles, boundaries, slabs and roofs all re-derive. Ops apply in order on the drawing, so an op may target
what an earlier op made (its handle is that op's id). A target that is no longer in the drawing gives an
`edit_target_missing` warning and the op is skipped: nothing is dropped silently.
"""

import math
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import Point, Polygon

from api.engine.canonical.model import Issue, Room, SourceRef
from api.engine.geometry2d.openings import Marker, Rect
from api.engine.geometry2d.walls import Segment
from api.engine.settings import DEFAULTS, Settings

F = Annotated[float, Field(allow_inf_nan=False)]
Pt = tuple[F, F]


def _axis(a: Pt, b: Pt) -> str | None:
    """"h" (constant y), "v" (constant x) or None (skewed or zero length), within the edit tolerance."""
    tol = DEFAULTS.edit_match_tolerance_mm
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    if dy <= tol < dx:
        return "h"
    if dx <= tol < dy:
        return "v"
    return None


def _need_line(a: Pt, b: Pt, what: str) -> None:
    if math.dist(a, b) <= DEFAULTS.edit_match_tolerance_mm:
        raise ValueError(f"{what} must have a length")


def _parallel(a: Pt, b: Pt, c: Pt, d: Pt) -> bool:
    """Whether a->b and c->d run along the same direction (either way), within a thousandth of a radian."""
    u, v = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
    return abs(u[0] * v[1] - u[1] * v[0]) <= 1e-3 * math.hypot(*u) * math.hypot(*v)


class _Frame:
    """A wall's own frame: s along start -> end, v across it (left of the direction), origin at its start."""

    def __init__(self, start: Pt, end: Pt):
        self.o, self.length = start, math.dist(start, end)
        self.u = ((end[0] - start[0]) / self.length, (end[1] - start[1]) / self.length)
        self.n = (-self.u[1], self.u[0])

    def to(self, p: Pt) -> tuple[float, float]:
        d = (p[0] - self.o[0], p[1] - self.o[1])
        return d[0] * self.u[0] + d[1] * self.u[1], d[0] * self.n[0] + d[1] * self.n[1]

    def at(self, s: float, v: float) -> Pt:
        return (self.o[0] + s * self.u[0] + v * self.n[0], self.o[1] + s * self.u[1] + v * self.n[1])


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WallRef(_M):
    """A wall as the model had it: its centreline, thickness and the source entity handles of its faces."""

    start: Pt
    end: Pt
    thickness: float = Field(gt=0, allow_inf_nan=False)
    handles: list[str] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _line(self) -> "WallRef":
        _need_line(self.start, self.end, "a wall")
        return self


class OpeningRef(_M):
    kind: Literal["door", "window"]
    start: Pt
    end: Pt
    handles: list[str] = Field(min_length=1, max_length=200)  # marker first, as in the model's sources

    @model_validator(mode="after")
    def _line(self) -> "OpeningRef":
        _need_line(self.start, self.end, "an opening")
        return self


class _Op(_M):
    id: str = Field(min_length=1, max_length=64)  # chosen by the client; becomes the edit's source handle


class _Dims(_M):
    height: float | None = Field(None, gt=0, allow_inf_nan=False)
    sill_height: float | None = Field(None, ge=0, allow_inf_nan=False)


class SetWall(_Op):
    op: Literal["set_wall"]
    target: WallRef
    start: Pt
    end: Pt
    thickness: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _line(self) -> "SetWall":
        _need_line(self.start, self.end, "a wall")
        return self


class AddWall(_Op):
    op: Literal["add_wall"]
    start: Pt
    end: Pt
    thickness: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _line(self) -> "AddWall":
        _need_line(self.start, self.end, "a wall")
        return self


class RemoveWall(_Op):
    op: Literal["remove_wall"]
    target: WallRef


class SetOpening(_Op, _Dims):
    op: Literal["set_opening"]
    target: OpeningRef
    kind: Literal["door", "window"]
    start: Pt
    end: Pt

    @model_validator(mode="after")
    def _same_axis(self) -> "SetOpening":
        _need_line(self.start, self.end, "an opening")
        if not _parallel(self.start, self.end, self.target.start, self.target.end):
            raise ValueError("an opening stays on its wall: its span must keep its direction")
        return self


class AddOpening(_Op, _Dims):
    op: Literal["add_opening"]
    wall: WallRef
    kind: Literal["door", "window"]
    start: Pt
    end: Pt

    @model_validator(mode="after")
    def _on_wall(self) -> "AddOpening":
        _need_line(self.start, self.end, "an opening")
        if not _parallel(self.start, self.end, self.wall.start, self.wall.end):
            raise ValueError("an opening must run along its wall")
        return self


class RemoveOpening(_Op):
    op: Literal["remove_opening"]
    target: OpeningRef


class RenameRoom(_Op):
    op: Literal["rename_room"]
    point: Pt  # any point inside the room
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not (v := v.strip()):
            raise ValueError("a room name cannot be empty")
        return v


EditOp = Annotated[
    SetWall | AddWall | RemoveWall | SetOpening | AddOpening | RemoveOpening | RenameRoom,
    Field(discriminator="op"),
]


class EditsRequest(_M):
    """The full ordered list of a floor's edits (replaces the stored list)."""

    edits: list[EditOp] = Field(max_length=DEFAULTS.max_edits)

    @model_validator(mode="after")
    def _unique(self) -> "EditsRequest":
        ids = [e.id for e in self.edits]
        if len(set(ids)) < len(ids):
            raise ValueError("edit ids must be unique")
        return self


def _ref(op_id: str) -> SourceRef:
    return SourceRef(format="edit", layer="edit", entity_handle=op_id)


def edit_ref(ref: SourceRef, edit_ids: set[str]) -> SourceRef:
    """A source reference made by an edit is marked as such (its layer is kept)."""
    return ref.model_copy(update={"format": "edit"}) if ref.entity_handle in edit_ids else ref


def _missing(op: _Op, what: str) -> Issue:
    return Issue(
        code="edit_target_missing", severity="warning",
        message=f"edit {op.id} ({op.op}): {what} is not in the drawing any more (it was changed since the "
        "edit was made); this edit was not applied",
        sources=[_ref(op.id)])


def _gone(op: _Op, m: Marker, why: str) -> Issue:
    return Issue(
        code="edit_opening_removed", severity="warning",
        message=f"edit {op.id} ({op.op}): the {m.kind} {m.ref.entity_handle} was removed: {why}",
        sources=[_ref(op.id), m.ref])


def _seg(s: Segment, tol: float):
    """(axis, constant coordinate, lo, hi) of an axis-parallel segment, else None."""
    (x0, y0), (x1, y1) = s.start, s.end
    if abs(y1 - y0) <= tol < abs(x1 - x0):
        return "h", (y0 + y1) / 2, min(x0, x1), max(x0, x1)
    if abs(x1 - x0) <= tol < abs(y1 - y0):
        return "v", (x0 + x1) / 2, min(y0, y1), max(y0, y1)
    return None


def _make(handle: str, layer: str, axis: str, c: float, lo: float, hi: float) -> Segment:
    return Segment(handle, layer, (lo, c) if axis == "h" else (c, lo),
                   (hi, c) if axis == "h" else (c, hi))


def _wall(start: Pt, end: Pt, t: float):
    """(axis, centre coordinate, lo, hi, rect) of a wall."""
    if _axis(start, end) == "h":
        c, lo, hi = (start[1] + end[1]) / 2, min(start[0], end[0]), max(start[0], end[0])
        return "h", c, lo, hi, (lo, c - t / 2, hi, c + t / 2)
    c, lo, hi = (start[0] + end[0]) / 2, min(start[1], end[1]), max(start[1], end[1])
    return "v", c, lo, hi, (c - t / 2, lo, c + t / 2, hi)


def _inside(p, r: Rect, tol: float) -> bool:
    return r[0] - tol <= p[0] <= r[2] + tol and r[1] - tol <= p[1] <= r[3] + tol


def _drop_across(segs: list[Segment], axis: str, rect: Rect, tol: float) -> list[Segment]:
    """Remove the lines running across a wall from one face to the other inside `rect` (jambs, end caps): what
    they closed is gone. A crossing wall's own lines are longer than that or run along the wall, so they stay."""
    cross = (rect[3] - rect[1]) if axis == "h" else (rect[2] - rect[0])

    def across(s: Segment) -> bool:
        a = _seg(s, tol)
        return (a is not None and a[0] != axis and a[3] - a[2] >= cross - tol
                and _inside(s.start, rect, tol) and _inside(s.end, rect, tol))

    return [s for s in segs if not across(s)]


def _clip(segs: list[Segment], ref: WallRef, tol: float):
    """Cut the wall's span out of the face lines it owns. (segments, layer, both faces found)."""
    axis, c, lo, hi, _ = _wall(ref.start, ref.end, ref.thickness)
    faces = (c - ref.thickness / 2, c + ref.thickness / 2)
    out, found, layer = [], [False, False], None
    for s in segs:
        a = _seg(s, tol)
        hit = a and s.handle in ref.handles and a[0] == axis and a[3] > lo + tol and a[2] < hi - tol
        side = [abs(a[1] - f) <= tol for f in faces] if hit else [False, False]
        if not any(side):
            out.append(s)
            continue
        found = [x or y for x, y in zip(found, side, strict=True)]
        layer = s.layer
        if lo - a[2] > tol:  # the face line goes on past the wall: that part stays
            out.append(_make(s.handle, s.layer, axis, a[1], a[2], lo))
        if a[3] - hi > tol:
            out.append(_make(s.handle, s.layer, axis, a[1], hi, a[3]))
    return out, layer, all(found)


def _markers_in(markers: list[Marker], rect: Rect, tol: float) -> list[Marker]:
    return [m for m in markers if _inside(((m.rect[0] + m.rect[2]) / 2, (m.rect[1] + m.rect[3]) / 2), rect, tol)]


def _close_gap(segs: list[Segment], axis: str, lo: float, hi: float, faces, layer: str, handle: str, tol: float):
    """Make the wall solid again across [lo, hi]: join the face lines either side of the gap (or extend one)."""
    for c in faces:
        left = right = None
        for i, s in enumerate(segs):
            a = _seg(s, tol)
            if a and a[0] == axis and abs(a[1] - c) <= tol:
                if abs(a[3] - lo) <= tol:
                    left = i
                elif abs(a[2] - hi) <= tol:
                    right = i
        keep = [s for i, s in enumerate(segs) if i not in (left, right)]
        if left is not None and right is not None:
            segs = [*keep, _make(segs[left].handle, segs[left].layer, axis, c, _seg(segs[left], tol)[2], _seg(segs[right], tol)[3])]
        elif left is not None:
            segs = [*keep, _make(segs[left].handle, segs[left].layer, axis, c, _seg(segs[left], tol)[2], hi)]
        elif right is not None:
            segs = [*keep, _make(segs[right].handle, segs[right].layer, axis, c, lo, _seg(segs[right], tol)[3])]
        else:
            segs = [*segs, _make(handle, layer, axis, c, lo, hi)]
    return segs


# --- walls and openings off the axes: the same steps in the wall's own frame (s along, v across) ---

def _par(s: Segment, fr: _Frame, tol: float):
    """(v, lo, hi) of a segment running along the frame's direction, else None."""
    (s0, v0), (s1, v1) = fr.to(s.start), fr.to(s.end)
    return ((v0 + v1) / 2, min(s0, s1), max(s0, s1)) if abs(v1 - v0) <= tol and abs(s1 - s0) > tol else None


def _quad(fr: _Frame, a: float, b: float, v0: float, v1: float) -> tuple[Pt, ...]:
    return (fr.at(a, v0), fr.at(b, v0), fr.at(b, v1), fr.at(a, v1))


def _bounds(pts) -> Rect:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _marker_at(kind: str, ref: SourceRef, fr: _Frame, a: float, b: float, v0: float, v1: float, inferred=False) -> Marker:
    """A marker over s in [a, b] across v0..v1 of the frame: a turned one when the frame is, else axis-aligned."""
    quad = _quad(fr, a, b, v0, v1)
    if _axis(fr.at(0, 0), fr.at(1, 0)) is None:
        return Marker(kind, ref, _bounds(quad), inferred, quad)
    return Marker(kind, ref, _bounds(quad), inferred)


def _clip_diag(segs: list[Segment], ref: WallRef, tol: float):
    """Cut the wall's span out of the face lines it owns (see _clip). (segments, layer, both faces found)."""
    fr, t = _Frame(ref.start, ref.end), ref.thickness
    out, found, layer = [], [False, False], None
    for sg in segs:
        a = _par(sg, fr, tol) if sg.handle in ref.handles else None
        side = [abs(a[0] - f) <= tol for f in (-t / 2, t / 2)] if a else [False, False]
        if not (a and any(side) and a[2] > tol and a[1] < fr.length - tol):
            out.append(sg)
            continue
        found = [x or y for x, y in zip(found, side, strict=True)]
        layer = sg.layer
        if a[1] < -tol:  # the face line goes on past the wall: that part stays
            out.append(Segment(sg.handle, sg.layer, fr.at(a[1], a[0]), fr.at(0, a[0])))
        if a[2] > fr.length + tol:
            out.append(Segment(sg.handle, sg.layer, fr.at(fr.length, a[0]), fr.at(a[2], a[0])))
    return out, layer, all(found)


def _drop_across_diag(segs: list[Segment], poly: Polygon, fr: _Frame, across: float, tol: float) -> list[Segment]:
    """_drop_across for a turned rectangle: lines not along it, as long as it is wide, lying inside it."""
    box = poly.buffer(tol)

    def crossing(sg: Segment) -> bool:
        return (_par(sg, fr, tol) is None and math.dist(sg.start, sg.end) >= across - tol
                and box.contains(Point(sg.start)) and box.contains(Point(sg.end)))

    return [sg for sg in segs if not crossing(sg)]


def _close_gap_diag(segs: list[Segment], fr: _Frame, lo: float, hi: float, faces, layer: str, handle: str, tol: float):
    """_close_gap in the frame: make the wall solid again across [lo, hi] on each face line v."""
    for v in faces:
        left = right = None
        for i, sg in enumerate(segs):
            a = _par(sg, fr, tol)
            if a and abs(a[0] - v) <= tol:
                if abs(a[2] - lo) <= tol:
                    left = i
                elif abs(a[1] - hi) <= tol:
                    right = i
        keep = [sg for i, sg in enumerate(segs) if i not in (left, right)]
        if left is not None and right is not None:
            segs = [*keep, Segment(segs[left].handle, segs[left].layer, segs[left].start, segs[right].end)
                    if _par(segs[left], fr, tol)[1] < _par(segs[right], fr, tol)[1]
                    else Segment(segs[left].handle, segs[left].layer, segs[right].start, segs[left].end)]
        elif left is not None:
            segs = [*keep, Segment(segs[left].handle, segs[left].layer, fr.at(_par(segs[left], fr, tol)[1], v), fr.at(hi, v))]
        elif right is not None:
            segs = [*keep, Segment(segs[right].handle, segs[right].layer, fr.at(lo, v), fr.at(_par(segs[right], fr, tol)[2], v))]
        elif not any((a := _par(sg, fr, tol)) and abs(a[0] - v) <= tol and a[1] <= lo + tol and a[2] >= hi - tol for sg in segs):
            segs = [*segs, Segment(handle, layer, fr.at(lo, v), fr.at(hi, v))]  # unless a line already runs across it
    return segs


def _faces_any(handle: str, layer: str, start: Pt, end: Pt, t: float) -> list[Segment]:
    fr = _Frame(start, end)
    return [Segment(handle, layer, fr.at(0, -t / 2), fr.at(fr.length, -t / 2)),
            Segment(handle, layer, fr.at(0, t / 2), fr.at(fr.length, t / 2))]


def _marker_span(m: Marker, fr: _Frame) -> tuple[float, float]:
    pts = m.quad or ((m.rect[0], m.rect[1]), (m.rect[2], m.rect[1]), (m.rect[2], m.rect[3]), (m.rect[0], m.rect[3]))
    ss = [fr.to(p)[0] for p in pts]
    return min(ss), max(ss)


def apply_geometry_edits(
    segments: list[Segment], markers: list[Marker], ops: Sequence, settings: Settings = DEFAULTS
) -> tuple[list[Segment], list[Marker], list[Issue]]:
    """Wall and opening ops on the reader's wall face segments and opening markers, in order."""
    tol = settings.edit_match_tolerance_mm
    segs, mks, issues = list(segments), list(markers), []
    wall_layer = settings.wall_layer

    def faces_of(handle, layer, start, end, t):
        axis, c, lo, hi, _ = _wall(start, end, t)
        return [_make(handle, layer, axis, c - t / 2, lo, hi), _make(handle, layer, axis, c + t / 2, lo, hi)]

    def centre(m: Marker) -> Pt:
        pts = m.quad or ((m.rect[0], m.rect[1]), (m.rect[2], m.rect[3]))
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    for op in ops:
        turned = (
            (op.op in ("remove_wall", "set_wall") and (_axis(op.target.start, op.target.end) is None
                                                       or (op.op == "set_wall" and _axis(op.start, op.end) is None)))
            or (op.op == "add_opening" and _axis(op.wall.start, op.wall.end) is None)
            or (op.op in ("remove_opening", "set_opening") and _axis(op.target.start, op.target.end) is None)
        )
        if turned:  # a wall or opening off the axes: the same edit in the wall's own frame
            if op.op in ("remove_wall", "set_wall"):
                t = op.target
                fr = _Frame(t.start, t.end)
                if _axis(t.start, t.end) is None:
                    clipped, layer, ok = _clip_diag(segs, t, tol)
                    poly = Polygon(_quad(fr, 0, fr.length, -t.thickness / 2, t.thickness / 2))
                    if ok:
                        segs = _drop_across_diag(clipped, poly, fr, t.thickness, tol)
                else:  # an axis-aligned wall made diagonal: clip with the axis rules
                    axis, _, lo, hi, rect = _wall(t.start, t.end, t.thickness)
                    clipped, layer, ok = _clip(segs, t, tol)
                    poly = Polygon(_quad(fr, 0, fr.length, -t.thickness / 2, t.thickness / 2))
                    if ok:
                        segs = _drop_across(clipped, axis, rect, tol)
                if not ok:
                    issues.append(_missing(op, "the wall"))
                    continue
                box = poly.buffer(tol)
                on_wall = [m for m in mks if box.contains(Point(centre(m)))]
                mks = [m for m in mks if m not in on_wall]
                if op.op == "remove_wall":
                    issues += [_gone(op, m, "it was in the removed wall") for m in on_wall]
                    continue
                new = _Frame(op.start, op.end)
                h = op.thickness / 2
                segs += _faces_any(op.id, layer, op.start, op.end, op.thickness)
                for m in on_wall:  # openings travel with their wall
                    a, b = _marker_span(m, fr)
                    if abs(new.length - fr.length) > tol:  # a length change: the opening keeps its place in the plan
                        pa, pb = (new.to(fr.at(x, 0)) for x in (a, b))
                        if abs(pa[1]) > tol or abs(pb[1]) > tol:
                            issues.append(_gone(op, m, "it no longer fits the edited wall"))
                            continue
                        a, b = pa[0], pb[0]
                    if a < -tol or b > new.length + tol:
                        issues.append(_gone(op, m, "it no longer fits the edited wall"))
                        continue
                    mks.append(_marker_at(m.kind, m.ref, new, a, b, -h, h, m.inferred))
            elif op.op == "add_opening":
                w = op.wall
                if not _clip_diag(segs, w, tol)[2]:
                    issues.append(_missing(op, "the wall the opening goes in"))
                    continue
                fr, half = _Frame(w.start, w.end), w.thickness / 2
                a, b = sorted(fr.to(p)[0] for p in (op.start, op.end))
                layer = settings.door_layer if op.kind == "door" else settings.window_layer
                mks.append(_marker_at(op.kind, SourceRef(format="edit", layer=layer, entity_handle=op.id), fr, a, b, -half, half))
            else:  # remove_opening / set_opening
                t = op.target
                m = next((m for m in mks if m.ref.entity_handle in t.handles), None)
                if m is None:
                    issues.append(_missing(op, "the opening"))
                    continue
                fr = _Frame(t.start, t.end)
                pts = m.quad or ((m.rect[0], m.rect[1]), (m.rect[2], m.rect[1]), (m.rect[2], m.rect[3]), (m.rect[0], m.rect[3]))
                lo, hi = _marker_span(m, fr)
                vs = [fr.to(p)[1] for p in pts]
                v0, v1 = min(vs), max(vs)
                layer = next((x.layer for x in segs if x.layer in settings.wall_layers), wall_layer)
                segs = _close_gap_diag(
                    _drop_across_diag(segs, Polygon(_quad(fr, lo, hi, v0, v1)), fr, v1 - v0, tol),
                    fr, lo, hi, (v0, v1), layer, op.id, tol)
                mks.remove(m)
                if op.op == "set_opening":
                    a, b = sorted(fr.to(p)[0] for p in (op.start, op.end))
                    mks.append(_marker_at(op.kind, SourceRef(format="edit", layer=m.ref.layer, entity_handle=op.id), fr, a, b, v0, v1))
            continue
        if op.op in ("remove_wall", "set_wall"):
            t = op.target
            axis, _, lo, hi, rect = _wall(t.start, t.end, t.thickness)
            clipped, layer, ok = _clip(segs, t, tol)
            if not ok:
                issues.append(_missing(op, "the wall"))
                continue
            segs = _drop_across(clipped, axis, rect, tol)
            on_wall = _markers_in(mks, rect, tol)
            mks = [m for m in mks if m not in on_wall]
            if op.op == "remove_wall":
                issues += [_gone(op, m, "it was in the removed wall") for m in on_wall]
                continue
            n_axis, _, n_lo, n_hi, n_rect = _wall(op.start, op.end, op.thickness)
            segs += faces_of(op.id, layer, op.start, op.end, op.thickness)
            for m in on_wall:  # openings travel with their wall
                m_lo, m_hi = (m.rect[0], m.rect[2]) if axis == "h" else (m.rect[1], m.rect[3])
                shift = n_lo - lo if abs((n_hi - n_lo) - (hi - lo)) <= tol else 0.0
                if n_axis != axis or m_lo + shift < n_lo - tol or m_hi + shift > n_hi + tol:
                    issues.append(_gone(op, m, "it no longer fits the edited wall"))
                    continue
                a, b = m_lo + shift, m_hi + shift
                moved = (a, n_rect[1], b, n_rect[3]) if n_axis == "h" else (n_rect[0], a, n_rect[2], b)
                mks.append(Marker(m.kind, m.ref, moved, m.inferred))
        elif op.op == "add_wall":
            segs += (faces_of if _axis(op.start, op.end) else _faces_any)(op.id, wall_layer, op.start, op.end, op.thickness)
        elif op.op == "add_opening":
            w = op.wall
            axis, c, _, _, _ = _wall(w.start, w.end, w.thickness)
            if not _clip(segs, w, tol)[2]:  # only to find its faces; nothing is kept
                issues.append(_missing(op, "the wall the opening goes in"))
                continue
            i = 0 if axis == "h" else 1
            a, b = sorted((op.start[i], op.end[i]))
            half = w.thickness / 2
            rect = (a, c - half, b, c + half) if axis == "h" else (c - half, a, c + half, b)
            layer = settings.door_layer if op.kind == "door" else settings.window_layer
            mks.append(Marker(op.kind, SourceRef(format="edit", layer=layer, entity_handle=op.id), rect))
        elif op.op in ("remove_opening", "set_opening"):
            t = op.target
            m = next((m for m in mks if m.ref.entity_handle in t.handles), None)
            if m is None:
                issues.append(_missing(op, "the opening"))
                continue
            axis = _axis(t.start, t.end)
            lo, hi = (m.rect[0], m.rect[2]) if axis == "h" else (m.rect[1], m.rect[3])
            faces = (m.rect[1], m.rect[3]) if axis == "h" else (m.rect[0], m.rect[2])
            layer = next((s.layer for s in segs if s.layer in settings.wall_layers), wall_layer)
            segs = _close_gap(_drop_across(segs, axis, m.rect, tol), axis, lo, hi, faces, layer, op.id, tol)
            mks.remove(m)
            if op.op == "set_opening":
                i = 0 if axis == "h" else 1
                a, b = sorted((op.start[i], op.end[i]))
                rect = (a, faces[0], b, faces[1]) if axis == "h" else (faces[0], a, faces[1], b)
                mks.append(Marker(op.kind, SourceRef(format="edit", layer=m.ref.layer, entity_handle=op.id), rect))
    return segs, mks, issues


def opening_dimensions(ops: Sequence) -> dict[str, tuple[float | None, float | None, bool, bool]]:
    """Per edited opening (its marker handle = the op id): the height and sill the user gave, if any, and whether
    its width and its offset really changed against the snapshot the edit started from (a new opening: both)."""
    tol = DEFAULTS.edit_match_tolerance_mm
    out = {}
    for o in ops:
        if o.op == "add_opening":
            out[o.id] = (o.height, o.sill_height, True, True)
        elif o.op == "set_opening":
            if _axis(o.start, o.end) is None:  # turned: the span's own length, and where its lower-y end lies
                lo = lambda a, b: min((a, b), key=lambda p: (p[1], p[0]))
                width = abs(math.dist(o.start, o.end) - math.dist(o.target.start, o.target.end)) > tol
                moved = math.dist(lo(o.start, o.end), lo(o.target.start, o.target.end)) > tol
                out[o.id] = (o.height, o.sill_height, width, moved)
                continue
            i = 0 if _axis(o.start, o.end) == "h" else 1
            new, old = sorted((o.start[i], o.end[i])), sorted((o.target.start[i], o.target.end[i]))
            out[o.id] = (o.height, o.sill_height, abs((new[1] - new[0]) - (old[1] - old[0])) > tol, abs(new[0] - old[0]) > tol)
    return out


def modified_thickness(ops: Sequence) -> set[str]:
    """Ids of the edits that give a wall a thickness the user chose (a new wall, or a changed thickness)."""
    tol = DEFAULTS.edit_match_tolerance_mm
    return {o.id for o in ops if o.op == "add_wall" or (o.op == "set_wall" and abs(o.thickness - o.target.thickness) > tol)}


def apply_room_edits(rooms: list[Room], ops: Sequence) -> tuple[list[Room], list[Issue]]:
    """Rename the room containing the point. Applied after rooms are found."""
    out, issues = list(rooms), []
    for op in (o for o in ops if o.op == "rename_room"):
        i = next((i for i, r in enumerate(out) if Polygon(r.polygon, r.holes).contains(Point(op.point))), None)
        if i is None:
            issues.append(_missing(op, "a room at that point"))
            continue
        out[i] = out[i].model_copy(update={"name": op.name, "name_source": "user_modified"})
    return out, issues
