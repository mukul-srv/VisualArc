"""Canonical building model: the contract between adapters and geometry.

Units: millimetres. Coordinates: plan X/Y, right-handed (ADR-001).
Every important value is a `Measured` carrying its provenance.
"""

import itertools
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.engine.settings import DEFAULTS

SCHEMA_VERSION = "0.5.0"

Provenance = Literal["source_extracted", "user_provided", "defaulted", "inferred"]
Point2 = tuple[float, float]


class _Model(BaseModel):
    # forbid unknown keys so schema drift fails loudly instead of being dropped
    model_config = ConfigDict(frozen=True, extra="forbid")


class Measured(_Model):
    value: float
    unit: Literal["mm"] = "mm"
    source: Provenance


class SourceRef(_Model):
    format: Literal["dxf"] = "dxf"
    layer: str
    entity_handle: str


class Issue(_Model):
    code: str
    severity: Literal["blocking", "warning"]
    message: str
    sources: list[SourceRef] = []


class LineGeometry(_Model):
    kind: Literal["line"] = "line"
    start: Point2
    end: Point2


def _axis(line: LineGeometry) -> int | None:
    """0 if the line runs along x, 1 if along y, None if skewed or degenerate."""
    tol = DEFAULTS.tolerance_mm
    dx = abs(line.end[0] - line.start[0])
    dy = abs(line.end[1] - line.start[1])
    if dy <= tol < dx:
        return 0
    if dx <= tol < dy:
        return 1
    return None


class Wall(_Model):
    id: str
    type: Literal["wall"] = "wall"
    centreline: LineGeometry
    thickness: Measured
    height: Measured | None  # None until supplied; missing height is a blocking issue
    sources: list[SourceRef]  # paired-line walls keep both boundary handles
    # None only when the role layers of its lines conflict (blocking issue)
    role: Literal["exterior", "interior"] | None = None
    role_source: Literal["source_extracted", "inferred"] | None = None

    @model_validator(mode="after")
    def _check_role(self) -> "Wall":
        if (self.role is None) != (self.role_source is None):
            raise ValueError(f"{self.id}: role and role_source go together")
        return self


class Junction(_Model):
    """Corner/T fill between paired-line walls; not drawn as such in the source."""

    id: str
    type: Literal["junction"] = "junction"
    polygon: list[Point2]  # closed ring, first point not repeated
    source: Literal["inferred"] = "inferred"
    wall_ids: list[str]  # walls it touches; height comes from these


class FloorBoundary(_Model):
    id: str
    type: Literal["floor_boundary"] = "floor_boundary"
    polygon: list[Point2]  # closed ring, first point not repeated
    sources: list[SourceRef]


class Ceiling(_Model):
    """Slab at floor elevation + user ceiling height, one per floor boundary."""

    id: str
    type: Literal["ceiling"] = "ceiling"
    polygon: list[Point2]  # same ring as its boundary
    # derived sum (floor elevation + ceiling height): never source_extracted
    elevation: Measured
    sources: list[SourceRef]  # the boundary's sources


# shortcut: model invariants use DEFAULTS.tolerance_mm, not a caller's Settings;
# pass it via validation context if tolerance ever becomes per-run.
class Opening(_Model):
    """Door or window in a host wall (ADR-002 Option B)."""

    id: str  # "opening-001", sorted by (span.start y, x)
    type: Literal["opening"] = "opening"
    kind: Literal["door", "window"]  # from the marker's layer
    wall_id: str  # merged host wall on the same Floor
    span: LineGeometry  # on host centreline, start = lower coordinate
    offset: Measured  # host.centreline.start -> span.start
    width: Measured  # == |span|
    height: Measured
    sill_height: Measured  # above floor elevation
    sources: list[SourceRef] = Field(min_length=1)  # marker first, then jamb lines

    @model_validator(mode="after")
    def _check(self) -> "Opening":
        if self.width.value <= 0 or self.height.value <= 0:
            raise ValueError(f"{self.id}: width and height must be > 0 mm")
        if self.sill_height.value < 0 or self.offset.value < 0:
            raise ValueError(f"{self.id}: sill_height and offset must be >= 0 mm")
        axis = _axis(self.span)
        if axis is None:
            raise ValueError(f"{self.id}: span must be axis-aligned and non-degenerate")
        if self.span.end[axis] < self.span.start[axis]:
            raise ValueError(f"{self.id}: span must start at the lower coordinate")
        length = math.dist(self.span.start, self.span.end)
        if abs(self.width.value - length) > DEFAULTS.tolerance_mm:
            raise ValueError(
                f"{self.id}: width {self.width.value} != span length {length}"
            )
        return self


class Floor(_Model):
    id: str
    name: str
    elevation: Measured
    ceiling_height: Measured | None = None  # None -> blocking when walls exist
    walls: list[Wall] = []
    junctions: list[Junction] = []
    boundaries: list[FloorBoundary] = []
    openings: list[Opening] = []
    ceilings: list[Ceiling] = []

    @model_validator(mode="after")
    def _check_ceiling(self) -> "Floor":
        if self.ceiling_height is not None and self.ceiling_height.value <= 0:
            raise ValueError(f"{self.id}: ceiling height must be > 0 mm")
        return self

    @model_validator(mode="after")
    def _check_openings(self) -> "Floor":
        tol = DEFAULTS.tolerance_mm
        ids = [o.id for o in self.openings]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.id}: duplicate opening ids")
        walls = {w.id: w for w in self.walls}
        runs: dict[str, list[tuple[float, float, str]]] = {}
        for o in self.openings:
            w = walls.get(o.wall_id)
            if w is None:
                raise ValueError(f"{o.id}: wall {o.wall_id!r} is not on {self.id}")
            c, axis = w.centreline, _axis(o.span)
            off = 1 - axis
            lo, hi = sorted((c.start[axis], c.end[axis]))
            if (
                _axis(c) != axis
                or abs(o.span.start[off] - c.start[off]) > tol
                or abs(o.span.end[off] - c.start[off]) > tol
                or o.span.start[axis] < lo - tol
                or o.span.end[axis] > hi + tol
            ):
                raise ValueError(f"{o.id}: span is not within {w.id}'s centreline")
            if abs(o.offset.value - math.dist(c.start, o.span.start)) > tol:
                raise ValueError(f"{o.id}: offset != distance from {w.id} start")
            top = o.sill_height.value + o.height.value
            if w.height is not None and top > w.height.value + tol:
                raise ValueError(f"{o.id}: sill + height exceeds {w.id} height")
            runs.setdefault(w.id, []).append(
                (o.span.start[axis], o.span.end[axis], o.id)
            )
        for spans in runs.values():
            spans.sort()
            for (_, hi, a), (lo, _, b) in itertools.pairwise(spans):
                if lo < hi - tol:
                    raise ValueError(f"{a} and {b} overlap along their host wall")
        return self


class Building(_Model):
    id: str
    floors: list[Floor] = []


class Project(_Model):
    schema_version: str = SCHEMA_VERSION
    id: str
    units: Literal["mm"] = "mm"
    source_file: str
    buildings: list[Building] = []
    issues: list[Issue] = []
