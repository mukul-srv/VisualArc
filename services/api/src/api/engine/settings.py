"""Engine thresholds and tolerances, in one place (T7, ADR-003).

Every value here changes what the engine accepts or how it interprets a drawing,
so each one says WHY it has its value. Change a default only with a reason
recorded in Document 08; pass a modified `Settings` to experiment instead.
All lengths are canonical millimetres (ADR-001).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BuildingPreset:
    """Nominal dimensions (mm) used, tagged `defaulted`, for values the user left out."""

    wall_height: float
    ceiling_height: float
    door_height: float
    window_height: float
    window_sill: float
    floor_to_floor: float  # next-floor elevation step when none is given
    # project parameters (engine/parameters.py); `roof_type` / `roof_pitch` (degrees) are
    # read by the roof step, stair and railing values by the stair/railing steps
    slab_thickness: float = 200.0
    roof_type: str = "flat"
    roof_pitch: float = 0.0
    stair_rise: float = 175.0
    stair_run: float = 280.0
    lintel_height: float = 2100.0  # opening head height above the floor
    railing_height: float = 900.0


@dataclass(frozen=True)
class Settings:
    # Layer names of the MVP-0 convention. Matched case-insensitively (the reader
    # upper-cases the entity's layer), so these must be written in upper case.
    wall_layer: str = "A-WALL"
    # Role layers: walls read exactly like wall_layer walls, but the layer names the
    # role (user decision: layer first, geometry only as fallback). Upper case.
    wall_role_layers: tuple[tuple[str, str], ...] = (
        ("A-WALL-EXTR", "exterior"),
        ("A-WALL-INTR", "interior"),
    )
    floor_layer: str = "A-FLOR"
    # Opening marker layers (ADR-002 §1): AIA names; the layer is the opening kind.
    door_layer: str = "A-DOOR"
    window_layer: str = "A-GLAZ"
    # Structure layers (project extension, not AIA text; the iso13567 subset has no codes for
    # them, so it keeps these names and further layers are mapped with Custom). Upper case.
    column_layer: str = "A-COLS"
    balcony_layer: str = "A-BALC"  # closed outline of a balcony or terrace slab
    column_extra: tuple[str, ...] = ()
    balcony_extra: tuple[str, ...] = ()
    # Railing member thickness (balcony edges); nominal, never read from a drawing. PROVISIONAL.
    railing_thickness_mm: float = 50.0

    # Per-project additions (conventions.py): more layers with the same meaning as the
    # primary ones above, and layers the user chose to ignore (still reported, never silent).
    # Upper case. Empty = the plain convention above.
    wall_extra: tuple[str, ...] = ()
    floor_extra: tuple[str, ...] = ()
    door_extra: tuple[str, ...] = ()
    window_extra: tuple[str, ...] = ()
    ignore_layers: tuple[str, ...] = ()

    # Opening height/sill used when no CLI flag supplies them; result is
    # provenance `defaulted` plus an opening_dimension_defaulted warning
    # (ADR-002 §5). Common residential values, sill above floor elevation.
    # PROVISIONAL: unverified against any standard (ADR-002 Q10).
    default_door_height_mm: float = 2100.0
    default_door_sill_mm: float = 0.0
    default_window_height_mm: float = 1200.0
    default_window_sill_mm: float = 900.0

    # Opening detail (medium): frame width, door leaf and window glass thickness. Nominal round
    # values (leaf 40 mm solid-core door, 24 mm double glazing unit), never read from a drawing,
    # recorded `defaulted`. PROVISIONAL: unverified against any standard.
    opening_frame_width_mm: float = 50.0
    door_leaf_thickness_mm: float = 40.0
    window_glass_thickness_mm: float = 24.0

    # Nominal presets per building type, the single source of truth (the web reads them
    # from GET /api/v1/presets). A missing height is filled from here, provenance
    # `defaulted` plus a warning naming the value. Round trade values, not a standard.
    # PROVISIONAL: unverified against any code or standard.
    building_presets: tuple[tuple[str, BuildingPreset], ...] = (
        ("residential", BuildingPreset(2700.0, 2700.0, 2100.0, 1200.0, 900.0, 3000.0, 200.0, "gable", 30.0)),
        ("commercial", BuildingPreset(3000.0, 2700.0, 2100.0, 1500.0, 900.0, 3600.0, 250.0, "flat", 0.0, railing_height=1100.0)),
    )

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

    # Role inference (no role layer): a wall face counts as lying on the exterior
    # ring of the wall union when it is within this distance of it. 1 mm absorbs
    # drafting noise while staying far below the thinnest wall (50 mm).
    role_face_tolerance_mm: float = 1.0

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

    # Floor split of a consolidated DXF (B8). Layer-prefix mode: a layer matching this
    # regex (group 1 = floor key) belongs to that floor; the rest of the name is mapped
    # by the normal layer rules. `|` is the usual AIA-style sheet separator.
    floor_prefix_pattern: str = r"^(L\d+)\|"
    # Spatial mode: wall/floor-boundary geometry closer than this (per axis) is one
    # floor. PROVISIONAL: 5 m is wider than the 1 m tile gap of the benchmark
    # fixtures and any gap inside one plan we have seen, but a detached garage 5 m
    # away would also split off; the user confirms every split, so it is a proposal.
    floor_gap_mm: float = 5000.0
    # Layers never reconstructed as floors (roof outlines, title blocks); fnmatch on
    # the upper-cased layer. Reported as content_not_reconstructed, never dropped.
    non_floor_layer_patterns: tuple[str, ...] = ("A-ROOF*", "*TTLB*", "*TITLE*")

    # Presentation only (never changes geometry): kind -> (sRGB hex, roughness).
    # Kinds: wall role, "wall_neutral" (junctions, and walls whose role is unresolved),
    # floor_boundary, slab, ceiling. Junctions get the neutral tone, not a wall role's:
    # they sit between walls of mixed roles, and a distinct tone keeps them visible
    # when checking the model. Mid-light, non-metal values so every kind reads
    # against the viewer background and under the selection highlight.
    material_palette: tuple[tuple[str, tuple[str, float]], ...] = (
        ("wall_exterior", ("#b5654a", 0.9)),
        ("wall_interior", ("#e6e0d4", 0.9)),
        ("wall_neutral", ("#a8a8a8", 0.9)),
        ("floor_boundary", ("#8c7b6b", 0.8)),
        ("slab", ("#7d7266", 0.9)),
        ("column", ("#9a9a94", 0.85)),
        ("balcony", ("#8f8579", 0.85)),
        ("balcony_railing", ("#4d5560", 0.6)),
        ("opening_frame", ("#5b4636", 0.7)),
        ("opening_leaf", ("#a9824f", 0.7)),
        ("opening_glass", ("#9fd0e6", 0.1)),
        ("ceiling", ("#f4f4f0", 0.95)),
    )

    def preset(self, building_type: str) -> BuildingPreset:
        return dict(self.building_presets)[building_type]

    @property
    def wall_layers(self) -> frozenset[str]:
        return frozenset({self.wall_layer, *(l for l, _ in self.wall_role_layers), *self.wall_extra})

    @property
    def floor_layers(self) -> frozenset[str]:
        return frozenset({self.floor_layer, *self.floor_extra})

    @property
    def door_layers(self) -> frozenset[str]:
        return frozenset({self.door_layer, *self.door_extra})

    @property
    def window_layers(self) -> frozenset[str]:
        return frozenset({self.window_layer, *self.window_extra})

    @property
    def column_layers(self) -> frozenset[str]:
        return frozenset({self.column_layer, *self.column_extra})

    @property
    def balcony_layers(self) -> frozenset[str]:
        return frozenset({self.balcony_layer, *self.balcony_extra})

    @property  # for messages: the primary layer, plus any user-mapped ones
    def wall_label(self) -> str:
        return ", ".join([self.wall_layer, *self.wall_extra])

    @property
    def floor_label(self) -> str:
        return ", ".join([self.floor_layer, *self.floor_extra])

    def __post_init__(self) -> None:
        if re.compile(self.floor_prefix_pattern).groups < 1:
            raise ValueError("floor_prefix_pattern needs a group for the floor key")
        if self.floor_gap_mm <= 0:
            raise ValueError("floor_gap_mm must be > 0 mm")
        # ADR-002 §5: reject impossible opening defaults up front, not per opening
        if min(self.default_door_height_mm, self.default_window_height_mm) <= 0:
            raise ValueError("default opening heights must be > 0 mm")
        if min(self.default_door_sill_mm, self.default_window_sill_mm) < 0:
            raise ValueError("default opening sills must be >= 0 mm")


DEFAULTS = Settings()
