"""Engine thresholds and tolerances, in one place (T7, ADR-003).

Every value here changes what the engine accepts or how it interprets a drawing,
so each one says WHY it has its value. Change a default only with a reason
recorded in Document 08; pass a modified `Settings` to experiment instead.
All lengths are canonical millimetres (ADR-001).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Layer names of the MVP-0 convention. Matched case-insensitively (the reader
    # upper-cases the entity's layer), so these must be written in upper case.
    wall_layer: str = "A-WALL"
    floor_layer: str = "A-FLOR"

    # Two parallel wall lines pair into a wall only if their distance is within
    # [min, max]. 50 mm admits thin partitions/linings; 600 mm admits thick
    # masonry/external walls. Outside this, parallel lines are more likely to be
    # unrelated (furniture, a corridor), so they are reported, not paired.
    # Also bounds junction size: a corner gap wider than wall_thickness_max_mm
    # in both directions is reported as an unexplained region.
    # PROVISIONAL: not yet reviewed by an architect (MC-3).
    wall_thickness_min_mm: float = 50.0
    wall_thickness_max_mm: float = 600.0

    # Geometric equality tolerance. Deliberately tiny (1e-6 mm): it only absorbs
    # float round-off from unit scaling, not drafting error. A 0.01 mm drafting
    # error is therefore NOT tolerated (line reported non-orthogonal / not
    # paired). Also reused as the "positive area" threshold (in mm2) for floor
    # polygons and junction/leftover regions.
    tolerance_mm: float = 1e-6

    # Input files larger than this are rejected before parsing (T4).
    # PROVISIONAL until T21 benchmarks; CLI --max-mb overrides per run.
    max_dxf_bytes: int = 50 * 1024 * 1024

    # An unmapped_layer issue lists at most this many entity refs per layer (the
    # total count is still in the message) so one noisy layer, e.g. thousands of
    # TEXT entities, cannot flood the report (T5).
    unmapped_ref_cap: int = 20


DEFAULTS = Settings()
