"""Canonical building model: the contract between adapters and geometry.

Units: millimetres. Coordinates: plan X/Y, right-handed (ADR-001).
Every important value is a `Measured` carrying its provenance.
"""

import itertools
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.engine.settings import DEFAULTS

# Vertical convention (0.8.0; ADR-001 addendum). A floor's `elevation` is the UNDERSIDE of its floor slab,
# the structural base: the grid/ground of a single-storey building. The slab fills base .. base + slab
# thickness inside the walls, so the FINISHED FLOOR (what you walk on, floor boundary, stair and ramp
# starts, column bases, balcony tops) is `elevation + slab thickness`. Walls start at the base, beside
# the slab, and rise to finished floor + wall height. Wall, ceiling, window-sill, lintel and railing
# heights are measured from the finished floor; the ceiling plane is finished floor + ceiling height;
# the roof sits on the wall tops. A floor without a slab (no floor boundary or no slab thickness) has
# its finished floor at `elevation`. The STOREY is the ceiling height: the next floor's slab underside
# is the ceiling plane and its finished floor is ceiling plane + slab, which is what a stair rises (ceiling
# height + slab thickness). Wall height may differ (walls above the ceiling form a void under the roof):
# stairs and the next floor still follow the ceiling, and `walls_above_ceiling` says so when either
# was given. Floor-to-floor stacking: elevations step by the floor-to-floor value.
# 0.7.1 (a slab per building part) was dropped again: a slab per floor boundary, as in 0.7.0; the
# optional Slab.boundary_ids / holes of 0.7.1 stay readable ("holes" is always empty now).
# 0.9.0: a floor boundary carries its provenance (`source_extracted` = drawn on the floor layer, `inferred` =
# derived from the closed outer wall perimeter when the drawing has no floor outline). Older files read as drawn.
# 0.10.0: user edits (Section D). Provenance gains `user_modified` (a value or name the user changed in the
# editor) and SourceRef.format gains "edit" (entity_handle = the edit op's id). Older files read unchanged.
SCHEMA_VERSION = "0.10.0"

Provenance = Literal["source_extracted", "user_provided", "defaulted", "inferred", "user_modified"]
Point2 = tuple[float, float]


class _Model(BaseModel):
    # forbid unknown keys so schema drift fails loudly instead of being dropped
    model_config = ConfigDict(frozen=True, extra="forbid")


class Measured(_Model):
    value: float
    unit: Literal["mm"] = "mm"
    source: Provenance


class SourceRef(_Model):
    format: Literal["dxf", "edit"] = "dxf"
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
    sources: list[SourceRef]  # the polyline drawn; for an inferred boundary, the walls around it
    source: Literal["source_extracted", "inferred"] = "source_extracted"


class Param(_Model):
    """One project parameter (engine/parameters.py) with its provenance: `user_provided`
    (the user's value) or `defaulted` (the building-type preset's)."""

    value: float | str
    unit: Literal["mm", "deg", "none"]
    source: Provenance


class Area(_Model):
    value: float
    unit: Literal["mm2"] = "mm2"
    source: Provenance


class Room(_Model):
    """Closed region enclosed by walls (inner faces). Name: the label inside it, else "Room N"."""

    id: str
    type: Literal["room"] = "room"
    name: str
    name_source: Provenance  # source_extracted (a drawing label) or defaulted ("Room N")
    polygon: list[Point2]
    holes: list[list[Point2]] = []  # free-standing wall pieces inside; `area` excludes them
    area: Area  # derived from the walls, so inferred
    label_sources: list[SourceRef] = []  # every label inside, reading order; the first names it

    @model_validator(mode="after")
    def _check(self) -> "Room":
        if self.area.value <= 0:
            raise ValueError(f"{self.id}: room area must be > 0")
        return self


class Slab(_Model):
    """Floor slab of one floor boundary: from the floor's `elevation` (structural base) up by
    `thickness`, whose top is the finished floor. The walls start at the same base beside it."""

    id: str
    type: Literal["slab"] = "slab"
    boundary_id: str | None = None  # the floor boundary it lies under
    boundary_ids: list[str] = []  # every floor boundary inside it (its top face is theirs)
    polygon: list[Point2]  # the floor boundary's ring
    holes: list[list[Point2]] = []  # 0.7.1 only; always empty now
    thickness: Measured
    sources: list[SourceRef]  # the boundary's sources

    @model_validator(mode="after")
    def _check(self) -> "Slab":
        if self.thickness.value <= 0:
            raise ValueError(f"{self.id}: slab thickness must be > 0 mm")
        return self


class Column(_Model):
    """Column from a closed axis-aligned rectangle or a circle on the column layer, extruded
    from the floor elevation to the ceiling-height parameter."""

    id: str
    type: Literal["column"] = "column"
    shape: Literal["rect", "circle"]
    polygon: list[Point2] | None = None  # rect: the 4 corners
    centre: Point2 | None = None  # circle
    radius: Measured | None = None  # circle
    height: Measured | None  # ceiling height (None only when that is missing: blocking)
    sources: list[SourceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "Column":
        rect = self.shape == "rect"
        own = (self.polygon,) if rect else (self.centre, self.radius)
        other = (self.centre, self.radius) if rect else (self.polygon,)
        if any(v is None for v in own) or any(v is not None for v in other):
            raise ValueError(f"{self.id}: {self.shape} column needs exactly its own footprint fields")
        if self.radius is not None and self.radius.value <= 0:
            raise ValueError(f"{self.id}: radius must be > 0 mm")
        return self


class Balcony(_Model):
    """Balcony or terrace: a slab outside the walls with a railing on its free edges.
    The drawing does not say which of the two it is, so no distinction is made."""

    id: str
    type: Literal["balcony"] = "balcony"
    polygon: list[Point2]
    thickness: Measured | None = None  # slab thickness; None = drawn as a flat surface
    railing_height: Measured | None = None  # None: no railing built (value missing)
    railing_thickness: Measured | None = None
    railings: list[LineGeometry] = []  # outline edges not shared with the building walls
    sources: list[SourceRef] = Field(min_length=1)


Direction = Literal["+x", "-x", "+y", "-y"]


class Stair(_Model):
    """Straight flight from a rectangle on the stair layer. `direction` (towards the top) comes
    from the arrow line; without it (or without the heights) nothing is built and an issue says
    why. Steps are solid blocks: `riser_count` risers of `riser_height`, `riser_count - 1`
    treads of `tread_depth` (the top riser meets the floor above)."""

    id: str
    type: Literal["stair"] = "stair"
    polygon: list[Point2]  # the 4 corners of the drawn flight
    direction: Direction | None = None
    total_rise: Measured | None = None  # ceiling height + slab thickness: up to the next finished floor (inferred)
    rise_param: Measured | None = None  # target riser height used to count the steps
    run_param: Measured | None = None  # nominal tread depth, compared with the drawing
    riser_count: int | None = None
    riser_height: Measured | None = None  # total_rise / riser_count (inferred)
    tread_depth: Measured | None = None  # drawn length / (riser_count - 1) (inferred)
    sources: list[SourceRef] = Field(min_length=1)  # outline first, then the arrow

    @model_validator(mode="after")
    def _check(self) -> "Stair":
        steps = (self.riser_count, self.riser_height, self.tread_depth)
        if any(v is None for v in steps) and any(v is not None for v in steps):
            raise ValueError(f"{self.id}: step fields go together")
        if self.riser_count is not None and self.direction is None:
            raise ValueError(f"{self.id}: steps need a direction")
        if self.riser_count is not None and self.riser_count < 2:
            raise ValueError(f"{self.id}: a stair needs at least 2 risers")
        return self


class Ramp(_Model):
    """Inclined slab over a rectangle on the ramp layer, rising `rise` towards `direction`."""

    id: str
    type: Literal["ramp"] = "ramp"
    polygon: list[Point2]
    direction: Direction | None = None
    rise: Measured | None = None  # ceiling height + slab thickness (inferred)
    thickness: Measured | None = None  # slab thickness parameter
    slope: float | None = None  # rise / drawn length, unitless
    sources: list[SourceRef] = Field(min_length=1)


class Roof(_Model):
    """Roof over one building outline: a flat slab, or a solid gable/hip volume above the top of
    the walls. `kind` is what was built, `requested` what the parameters asked for (they differ
    when an unsupported outline fell back to flat, with an issue). Pitched: `polygon` is the
    outline, the roof extends `overhang` beyond it on every side (0 for a drawn roof-plan outline,
    which already is the roof edge) and the ridge rises
    `ridge_height` above the eaves plane (half the overall short span x tan pitch)."""

    id: str
    type: Literal["roof"] = "roof"
    kind: Literal["flat", "gable", "hip"]
    requested: Literal["flat", "gable", "hip"]
    polygon: list[Point2]
    outline_source: Literal["roof_layer", "walls"]
    base_elevation: Measured | None = None  # floor elevation + wall height (inferred); None: no walls
    thickness: Measured | None = None  # flat roofs
    overhang: Measured | None = None  # pitched roofs
    pitch: Param | None = None  # pitched roofs, degrees
    ridge_axis: Literal["x", "y"] | None = None  # pitched roofs: the ridge runs along it
    ridge_height: Measured | None = None  # pitched roofs (inferred)
    type_param: Param | None = None  # the roof_type parameter with its provenance
    sources: list[SourceRef] = []  # roof-plan outline; empty when taken from the walls


class Ceiling(_Model):
    """Slab at floor elevation + user ceiling height, one per floor boundary."""

    id: str
    type: Literal["ceiling"] = "ceiling"
    polygon: list[Point2]  # same ring as its boundary
    # derived sum (floor elevation + ceiling height): never source_extracted
    elevation: Measured
    height: Measured | None = None  # the ceiling-height parameter it was built from
    sources: list[SourceRef]  # the boundary's sources


# shortcut: model invariants use DEFAULTS.tolerance_mm, not a caller's Settings;
# pass it via validation context if tolerance ever becomes per-run.
class Swing(_Model):
    """Door swing read from the arc symbol on the door layer; the leaf is modelled closed."""

    hinge: Literal["start", "end"]  # the span end the arc is centred on (start = lower coordinate)
    opens_toward: Literal["+x", "-x", "+y", "-y"]  # plan direction the leaf swings to
    source: SourceRef  # the arc


class OpeningDetail(_Model):
    """Medium detail (frame + one panel), all nominal Settings values, never read from the drawing.
    Frame: `frame_width` wide around the opening (jambs + head; a window also a sill), full wall
    depth. Panel: a door leaf or window glass box, `panel_thickness` thick, centred in the wall."""

    frame_width: Measured
    panel: Literal["leaf", "glass"]
    panel_thickness: Measured

    @model_validator(mode="after")
    def _check(self) -> "OpeningDetail":
        if self.frame_width.value <= 0 or self.panel_thickness.value <= 0:
            raise ValueError("frame width and panel thickness must be > 0 mm")
        return self


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
    swing: Swing | None = None  # doors only; None = no arc symbol found (never guessed)
    detail: OpeningDetail | None = None  # None = opening too small for frame + panel

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


class PlanOffset(_Model):
    """Translation applied when a floor was split out of a consolidated drawing:
    plan = source - offset. Pure translation, so no dimension changes."""

    x: float
    y: float
    unit: Literal["mm"] = "mm"
    source: Provenance


class Floor(_Model):
    id: str
    name: str
    elevation: Measured  # underside of the floor slab (see the vertical convention at the top)
    ceiling_height: Measured | None = None  # None -> blocking when walls exist
    walls: list[Wall] = []
    junctions: list[Junction] = []
    boundaries: list[FloorBoundary] = []
    openings: list[Opening] = []
    ceilings: list[Ceiling] = []
    slabs: list[Slab] = []
    rooms: list[Room] = []
    columns: list[Column] = []
    balconies: list[Balcony] = []
    stairs: list[Stair] = []
    roofs: list[Roof] = []
    ramps: list[Ramp] = []
    plan_offset: PlanOffset | None = None  # None = plan coordinates are the source's

    @property
    def finished_level_mm(self) -> float:
        """Top of the floor slab: what is walked on; elevation itself when there is no slab."""
        return self.elevation.value + max((s.thickness.value for s in self.slabs), default=0.0)

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
    parameters: dict[str, Param] = {}
