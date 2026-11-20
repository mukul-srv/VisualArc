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
    # Opening marker layers (ADR-002 §1): AIA names; the layer is the opening kind.
    door_layer: str = "A-DOOR"
    window_layer: str = "A-GLAZ"

    # Opening height/sill used when no CLI flag supplies them; result is
    # provenance `defaulted` plus an opening_dimension_defaulted warning
    # (ADR-002 §5). Common residential values, sill above floor elevation.
    # PROVISIONAL: unverified against any standard (ADR-002 Q10).
    default_door_height_mm: float = 2100.0
    default_door_sill_mm: float = 0.0
    default_window_height_mm: float = 1200.0
    default_window_sill_mm: float = 900.0

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

    # Extrusion (OCS normal) counts as parallel to Z when |x| and |y| are within
    # this. Unitless direction cosine, NOT millimetres, so it must not share
    # tolerance_mm. 1e-6 absorbs float round-off in a normalised vector while a
    # 1e-4 tilt (about 0.006 deg, but ~0.1 mm over 1 m) is flagged rather than
    # silently flattened onto the plan.
    extrusion_tolerance: float = 1e-6

    # Input limits (T4, T21a). All PROVISIONAL (approved at MC-8 for the local MVP):
    # derived from synthetic, regular benchmark fixtures only, not validated against
    # representative drawings or hosted infrastructure. Interpretation time grows
    # ~cubically with wall pieces (known debt: docs T21 report), so what is capped is
    # what drives cost. Rejected before interpretation, as InputError (exit 3 / 422).
    # File size is a backstop (~170 B/entity in the fixtures); CLI --max-mb overrides.
    max_dxf_bytes: int = 5 * 1024 * 1024
    max_entities: int = 5000  # all modelspace entities; backstop
    max_wall_segments: int = 600  # LINEs + polyline edges on the wall layer (~7 s)
    max_opening_markers: int = 120  # LWPOLYLINEs on door/window layers (ratio-derived)

    # An unmapped_layer issue lists at most this many entity refs per layer (the
    # total count is still in the message) so one noisy layer, e.g. thousands of
    # TEXT entities, cannot flood the report (T5).
    unmapped_ref_cap: int = 20

    def __post_init__(self) -> None:
        # ADR-002 §5: reject impossible opening defaults up front, not per opening
        if min(self.default_door_height_mm, self.default_window_height_mm) <= 0:
            raise ValueError("default opening heights must be > 0 mm")
        if min(self.default_door_sill_mm, self.default_window_sill_mm) < 0:
            raise ValueError("default opening sills must be >= 0 mm")


DEFAULTS = Settings()
