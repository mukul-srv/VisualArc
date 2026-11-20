"""Canonical building model: the contract between adapters and geometry.

Units: millimetres. Coordinates: plan X/Y, right-handed (ADR-001).
Every important value is a `Measured` carrying its provenance.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "0.2.0"

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


class Wall(_Model):
    id: str
    type: Literal["wall"] = "wall"
    centreline: LineGeometry
    thickness: Measured
    height: Measured | None  # None until supplied; missing height is a blocking issue
    sources: list[SourceRef]  # paired-line walls keep both boundary handles


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


class Floor(_Model):
    id: str
    name: str
    elevation: Measured
    walls: list[Wall] = []
    junctions: list[Junction] = []
    boundaries: list[FloorBoundary] = []


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
