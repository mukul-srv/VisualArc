"""DXF -> canonical Project, MVP-0 convention.

Walls = paired parallel LINE/LWPOLYLINE segments on A-WALL; floors = closed
LWPOLYLINE on A-FLOR; openings = closed rectangular LWPOLYLINE markers on
A-DOOR/A-GLAZ filling wall gaps (ADR-002). Everything is converted to mm via
$INSUNITS.
"""
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from fnmatch import fnmatchcase
from itertools import pairwise
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezbbox
from ezdxf import units
from shapely.geometry import Polygon
from shapely.ops import unary_union

from api.engine.adapters.dxf.interpret import classify_block, dimension_check
from api.engine.adapters.dxf.split import FloorScope, detect_floors, strip_floor_prefix
from api.engine.canonical.model import (
    Area,
    Balcony,
    Building,
    Ceiling,
    Column,
    Floor,
    FloorBoundary,
    Issue,
    Junction,
    LineGeometry,
    Measured,
    Param,
    PlanOffset,
    Project,
    Ramp,
    Roof,
    Room,
    Slab,
    SourceRef,
    Stair,
    Suggestion,
    Wall,
)
from api.engine.conventions import layer_hint, layer_hint_role
from api.engine.edits import (
    apply_geometry_edits,
    apply_room_edits,
    edit_ref,
    modified_thickness,
    opening_dimensions,
)
from api.engine.geometry2d.balconies import find_balconies
from api.engine.geometry2d.floor import closed_outer_perimeter, floor_issue
from api.engine.geometry2d.openings import (
    Marker,
    SwingArc,
    _bbox,
    build_openings,
    cut_walls_at_markers,
    cut_walls_at_turned_markers,
    door_swings,
    marker_quad,
    marker_rect,
    on_marker_boundary,
    resolve_openings,
)
from api.engine.geometry2d.role import resolve_roles
from api.engine.geometry2d.roofs import Outline as RoofOutline
from api.engine.geometry2d.roofs import plan_roofs, ridge_height, wall_outlines
from api.engine.geometry2d.rooms import Label, find_rooms
from api.engine.geometry2d.stairs import Arrow, Outline, find_flights
from api.engine.geometry2d.walls import Segment, heal_gaps, pair_walls
from api.engine.parameters import PARAMS
from api.engine.settings import DEFAULTS, Settings

# user-facing --units choices -> $INSUNITS code (kept small and explicit)
USER_UNITS = {
    "mm": units.MM,
    "cm": units.CM,
    "m": units.M,
    "in": units.IN,
    "ft": units.FT,
}


BLANK_TRACE = "visual_arc:blank-trace"  # $PROJECTNAME of the empty DXF a trace-from-image floor starts from


def make_blank_dxf(path: Path) -> None:
    """The source of a floor that is traced over an underlay: an empty mm drawing, marked as such. Without
    the mark an empty drawing stays a blocking `no_plan_geometry`."""
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$PROJECTNAME"] = BLANK_TRACE
    doc.saveas(path)


class InputError(ValueError):
    """Expected bad input (not a DXF, corrupt, too large): report, don't traceback."""


def _infer_boundaries(paired, pieces, rooms, settings: Settings):
    """Floor boundaries for a floor whose drawing has no floor outline at all: the interior of each space
    the walls close (inner wall faces), the same regions the rooms are built from, but only inside the closed
    OUTER wall loop: closed rooms behind an open outer wall are not a floor. Not closed, nothing is
    inferred and an issue says so. The boundary's sources are the walls that enclose it."""
    cap = settings.unmapped_ref_cap
    out = []
    inside = closed_outer_perimeter(paired, pieces, settings)
    for p in rooms if inside is not None else []:
        ring = Polygon(p.polygon)
        if not ring.is_valid or ring.area <= settings.tolerance_mm or not inside.buffer(settings.tolerance_mm).covers(ring):
            continue
        refs = list(dict.fromkeys(
            s.ref for w in paired if w.rect().distance(ring) <= settings.tolerance_mm for s in w.sources))
        out.append(FloorBoundary(id=f"fb-{len(out) + 1:03d}", polygon=p.polygon, sources=refs[:cap],
                                 source="inferred"))
    if not out:
        return [], Issue(
            code="floor_boundary_not_inferred",
            severity="warning",
            message="the drawing has no floor outline and its outer walls do not form a closed loop, so no "
            "floor boundary could be inferred: there is no slab, ceiling or walking surface. Close the "
            "outer wall outline, or draw the floor as a closed polyline on the floor layer",
        )
    return out, Issue(
        code="floor_boundary_inferred",
        severity="warning",
        message=f"the drawing has no floor outline: {len(out)} floor boundary polygon(s) inferred from the "
        "closed wall perimeter (the interior faces of the walls around each enclosed space). Check them, "
        "or draw the floor as a closed polyline on the floor layer to replace them",
        sources=list(dict.fromkeys(r for b in out for r in b.sources))[:cap],
    )


def _block_rect(e, mm, settings: Settings):
    """Footprint of an INSERT as a plan rectangle (mm): the extents of its geometry without ARCs
    (swing symbols). None when empty, flat (a line), or the block is rotated off the axes."""
    rot = getattr(e.dxf, "rotation", 0.0) % 90
    if min(rot, 90 - rot) > 1e-6 or _extrusion_issue(e, settings):
        return None
    try:
        box = ezbbox.extents(v for v in e.virtual_entities() if v.dxftype() != "ARC")
    except (ValueError, TypeError, AttributeError, ezdxf.DXFError):
        return None
    if not box.has_data:
        return None
    (x0, y0), (x1, y1) = mm(box.extmin), mm(box.extmax)
    tol = settings.tolerance_mm
    return (x0, y0, x1, y1) if x1 - x0 > tol and y1 - y0 > tol else None


def _recognise(doc, e, k: float, cache: dict, settings: Settings):
    """Block symbol recognition for an INSERT, classified once per (block, scale) from the block definition,
    so every rotated copy of a block gets the same answer. Non-uniform scaling is not read."""
    sx, sy = abs(e.dxf.get("xscale", 1.0)), abs(e.dxf.get("yscale", 1.0))
    if abs(sx - sy) > settings.block_rel_tolerance * max(sx, sy, 1e-9):
        return None
    key = (e.dxf.name, round(sx, 6))
    if key not in cache:
        block = doc.blocks.get(e.dxf.name)
        cache[key] = None if block is None else classify_block(list(block), e.dxf.name, k * sx, settings)
    return cache[key]


def load_doc(path: Path, max_bytes: int = DEFAULTS.max_dxf_bytes):
    if not path.is_file():
        raise InputError(f"not a readable file: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise InputError(
            f"file is {size / 2**20:.1f} MB, limit {max_bytes / 2**20:g} MB (provisional)"
        )
    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError as e:
        raise InputError(f"corrupt or truncated DXF: {e}") from e
    except ezdxf.DXFError as e:
        raise InputError(f"not a DXF file: {e}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise InputError(f"not a DXF file or unreadable: {e}") from e
    except StopIteration as e:  # ezdxf's tag loader runs out inside a header
        raise InputError("corrupt or truncated DXF: unexpected end of file") from e


def check_complexity(doc, settings: Settings = DEFAULTS) -> None:
    """Reject drawings above the provisional complexity limits (T21a), BEFORE the
    expensive interpretation. Counts what drives cost: wall-layer segments (a
    polyline contributes its edges) and opening markers, plus total entities."""
    msp = doc.modelspace()
    if len(msp) > settings.max_entities:
        raise InputError(
            f"drawing has {len(msp)} entities, limit is {settings.max_entities} "
            "(provisional; see the T21 benchmark report)"
        )
    opening_layers = settings.door_layers | settings.window_layers
    segments = markers = 0
    for e in msp:
        layer, kind = strip_floor_prefix(e.dxf.layer, settings).upper(), e.dxftype()
        if layer in settings.wall_layers:
            if kind == "LINE":
                segments += 1
            elif kind == "LWPOLYLINE":
                segments += len(e) if e.closed else len(e) - 1
        elif layer in opening_layers and kind == "LWPOLYLINE":
            markers += 1
    for count, limit, what in (
        (
            segments,
            settings.max_wall_segments,
            f"wall segments on {settings.wall_label}",
        ),
        (markers, settings.max_opening_markers, "opening markers"),
    ):
        if count > limit:
            raise InputError(
                f"drawing has {count} {what}, limit is {limit} "
                "(provisional; see the T21 benchmark report)"
            )


def resolve_scale(doc, user_units: str | None = None, override: bool = False) -> float | None:
    """Drawing units -> mm, or None when the units are missing, conflicting or
    unsupported (read_dxf reports those as blocking issues). `override`: the user's units
    replace a header they say is wrong."""
    code = doc.header.get("$INSUNITS", 0)
    user = USER_UNITS[user_units] if user_units else None
    if isinstance(code, bool) or not isinstance(code, int) or (code and user and code != user and not override):
        return None
    try:
        return units.conversion_factor((user if override and user else code or user), units.MM) if code or user else None
    except (TypeError, ValueError):
        return None


def _ref(e) -> SourceRef:
    return SourceRef(layer=e.dxf.layer, entity_handle=e.dxf.handle)


def _wcs_xy(e) -> list[tuple[float, float]]:
    """LWPOLYLINE vertices in world XY (applies OCS extrusion and elevation)."""
    return [(v.x, v.y) for v in e.vertices_in_wcs()]


def _extrusion_issue(e, settings: Settings) -> Issue | None:
    """Only extrusion (0,0,+-1) maps onto the plan; anything else is not guessed."""
    x, y, _ = e.dxf.extrusion
    if (
        abs(x) <= settings.extrusion_tolerance
        and abs(y) <= settings.extrusion_tolerance
    ):
        return None
    return Issue(
        code="unsupported_extrusion",
        severity="warning",
        message=f"{e.dxftype()} {e.dxf.handle} has extrusion "
        f"{tuple(e.dxf.extrusion)} not parallel to Z; cannot be placed in "
        "the plan, ignored",
        sources=[_ref(e)],
    )


def _is_closed(e, tol: float) -> bool:
    """Closed flag, or first vertex repeated at the end."""
    pts = e.get_points("xy")
    return bool(e.closed) or (len(pts) > 1 and math.dist(pts[0], pts[-1]) <= tol)


def _arc_issue(e) -> Issue:
    return Issue(
        code="unsupported_arc",
        severity="warning",
        message=f"{e.dxftype()} {e.dxf.handle} has arc segments; "
        "unsupported in MVP-0, ignored",
        sources=[_ref(e)],
    )


def _unit_label(code: int) -> str:
    # ezdxf's unit_name maps every unlisted code to "unitless", which misleads
    try:
        return units.InsertUnits(code).name
    except (TypeError, ValueError):
        return "unknown"


def _no_plan_geometry(doc, settings: Settings) -> list[Issue]:
    """Blocking issue when nothing in the file lies on a layer the reader builds a plan from: a title
    sheet, a detail or a differently layered drawing. Nothing is interpreted."""
    plan = settings.wall_layers | settings.floor_layers
    if any(e.dxf.layer.upper() in plan for e in doc.modelspace()):
        return []
    return [
        Issue(
            code="no_plan_geometry",
            severity="blocking",
            message="the drawing has no geometry on a wall or floor layer, so it does not look like a "
            f"floor plan (expected layers: {settings.wall_label}); if it is one, map its layers "
            "under Layer conventions",
        )
    ]


def _units_unsupported(project: dict, value) -> Project:
    return Project(
        **project,
        issues=[
            Issue(
                code="units_unsupported",
                severity="blocking",
                message=f"header $INSUNITS={value!r} is not a supported unit "
                "(supported: mm, cm, m, in, ft); supply a drawing in a supported "
                "unit. --units only applies when the header is missing",
            )
        ],
    )


def read_dxf(
    path: Path,
    wall_height: float | None = None,
    max_bytes: int | None = None,
    user_units: str | None = None,
    units_override: bool = False,  # the user says the header's units are wrong: theirs are used
    door_height: float | None = None,
    window_height: float | None = None,
    window_sill: float | None = None,
    ceiling_height: float | None = None,
    settings: Settings = DEFAULTS,
    floor_id: str = "floor-0",
    floor_name: str = "Level 0",
    floor_elevation: float | None = None,  # mm; None = defaulted 0 + warning
    scope: FloorScope | None = None,  # one confirmed floor of a consolidated DXF
    building_type: str | None = None,  # None: no presets, missing heights block (CLI)
    elevation_assumed: str | None = None,  # why floor_elevation is an assumption, if it is
    params: dict[str, float | str] | None = None,  # user-given project parameters (parameters.py)
    roof: bool = True,  # False: not the top floor of its project, so no roof
    edits: Sequence = (),  # the user's edits of this floor, in order (engine/edits.py)
) -> Project:
    if building_type is not None and building_type not in dict(settings.building_presets):
        raise ValueError(f"unknown building type {building_type!r}")
    preset = settings.preset(building_type) if building_type else None
    if preset:  # opening defaults follow the building type; still tagged `defaulted`
        settings = replace(
            settings,
            default_door_height_mm=preset.door_height,
            default_window_height_mm=preset.window_height,
            default_window_sill_mm=preset.window_sill,
        )
    for name, v in (
        ("wall height", wall_height),
        ("door height", door_height),
        ("window height", window_height),
        ("ceiling height", ceiling_height),
    ):
        if v is not None and v <= 0:
            raise ValueError(f"{name} must be > 0 mm, got {v}")
    if window_sill is not None and window_sill < 0:
        raise ValueError(f"window sill must be >= 0 mm, got {window_sill}")
    given = {k: v for k, v in {"ceiling_height": ceiling_height, "window_sill": window_sill,
                               "wall_height": wall_height, **(params or {})}.items()
             if v is not None}
    if unknown := set(given) - set(PARAMS):
        raise ValueError(f"unknown parameters {sorted(unknown)}")
    if given.get("slab_thickness", 1) <= 0:
        raise ValueError("slab thickness must be > 0 mm")
    doc = load_doc(path, settings.max_dxf_bytes if max_bytes is None else max_bytes)
    check_complexity(doc, settings)
    blank = doc.header.get("$PROJECTNAME") == BLANK_TRACE and len(doc.modelspace()) == 0  # see make_blank_dxf
    wall_layers, floor_layers = settings.wall_layers, settings.floor_layers
    ignored = set(settings.ignore_layers)
    ref_cap = settings.unmapped_ref_cap
    project = {"id": path.stem, "source_file": path.name}

    insunits = doc.header.get("$INSUNITS", 0)
    if isinstance(insunits, bool) or not isinstance(insunits, int):
        return _units_unsupported(project, insunits)
    user_code = USER_UNITS[user_units] if user_units else None
    overridden = bool(user_code and insunits and insunits != user_code and units_override)
    if user_code and insunits and insunits != user_code and not units_override:
        return Project(
            **project,
            issues=[
                Issue(
                    code="units_conflict",
                    severity="blocking",
                    message=f"--units {user_units} conflicts with header $INSUNITS="
                    f"{insunits} ({_unit_label(insunits)}); fix the drawing or drop --units. "
                    "If the header is wrong, say so explicitly (--units-override) and your units are used",
                )
            ],
        )
    if not insunits and not user_code:
        return Project(
            **project,
            issues=[
                *_no_plan_geometry(doc, settings),
                Issue(
                    code="units_missing",
                    severity="blocking",
                    message="$INSUNITS is not set; supply --units, refusing to guess",
                )
            ],
        )
    # header agrees with --units: stays source_extracted; only a missing header
    # makes the scale depend on the user
    from_user = not insunits or overridden
    try:
        k = units.conversion_factor(user_code if from_user else insunits, units.MM)
    except (
        TypeError,
        ValueError,
    ):  # e.g. 21 US survey feet, or a code not in the table
        return _units_unsupported(project, insunits)

    # The floor offset is applied here, at the single point where coordinates enter
    # (after unit scaling, before every geometry rule): downstream code sees plain
    # plan coordinates, and a pure translation cannot change any length or thickness.
    ox, oy = scope.offset if scope else (0.0, 0.0)

    def mm(p) -> tuple[float, float]:
        return (p[0] * k - ox, p[1] * k - oy)

    issues: list[Issue] = []
    if overridden:
        issues.append(
            Issue(
                code="units_overridden",
                severity="warning",
                message=f"header $INSUNITS={insunits} ({_unit_label(insunits)}) was overridden: "
                f"scaled to mm using the units you gave ({user_units}, user_provided)",
            )
        )
    elif from_user:
        issues.append(
            Issue(
                code="units_user_provided",
                severity="warning",
                message=f"$INSUNITS is not set; scaled to mm using user-supplied "
                f"--units {user_units}",
            )
        )
    if scope is None:  # a consolidated file must be split and confirmed first
        split = detect_floors(doc, k, settings)
        if len(split.candidates) > 1:
            keys = ", ".join(c.key for c in split.candidates)
            return Project(
                **project,
                issues=[
                    *issues,  # the units note too: the form keys the units override on it
                    Issue(
                        code="floor_split_unconfirmed",
                        severity="blocking",
                        message=f"drawing holds {len(split.candidates)} floor candidates "
                        f"({keys}); confirm each floor's name, elevation and offset "
                        "(POST /api/v1/uploads/{id}/split) before generating",
                    ),
                    *split.issues,
                    *dimension_check(doc.modelspace(), k, settings),  # wrong units often show as a split
                ],
            )

    segments: list[Segment] = []
    boundaries: list[FloorBoundary] = []
    floor_layer_seen = False  # anything on a floor-outline layer: the user's own outline rules, no autofill
    unmapped: dict[str, list] = {}  # layer -> entities, in drawing order
    opening_kind = {
        **dict.fromkeys(settings.window_layers, "window"),
        **dict.fromkeys(settings.door_layers, "door"),
    }
    user_ignored: dict[str, list] = {}  # layer -> entities the user mapped to "ignore"
    markers: list[Marker] = []
    block_markers: dict[str, list[SourceRef]] = {}  # block name -> its INSERTs used as markers
    decorative: dict[str, list] = {}  # opening layer -> ignored symbol entities
    swings = []  # ARCs on the door layer (orphan check)
    arc_centres: list[tuple[float, float]] = []  # centres of door-swing-like ARCs, loose or inside blocks (mm)
    labels: list[Label] = []  # TEXT/MTEXT: room-name candidates, placed later
    column_layers, balcony_layers = settings.column_layers, settings.balcony_layers
    cols: list[tuple] = []  # (ref, "rect", Rect) | (ref, "circle", centre, radius mm)
    balc: list[tuple] = []  # (ref, ring)
    stair_layers, ramp_layers = settings.stair_layers, settings.ramp_layers
    outlines: list[Outline] = []
    arrows: list[Arrow] = []
    roof_polys: list[tuple] = []  # (ref, ring) on the roof-plan layer
    rec_cache: dict[tuple, object] = {}  # (block name, scale) -> its recognition, classified once
    symbols: dict[tuple, list] = {}  # (block name, layer, recognition) -> its INSERTs
    for e in doc.modelspace():
        if scope and e.dxf.handle not in scope.handles:
            continue
        layer, kind = strip_floor_prefix(e.dxf.layer, settings).upper(), e.dxftype()
        if kind == "INSERT":  # a block holding an ARC may be a door symbol: evidence only, where a gap is
            try:
                arc_centres += [mm(a.ocs().to_wcs(a.dxf.center)) for a in e.virtual_entities() if a.dxftype() == "ARC"]
            except (ValueError, TypeError, AttributeError, ezdxf.DXFError):
                pass
        elif kind == "ARC" and layer in settings.door_layers:
            arc_centres.append(mm(e.ocs().to_wcs(e.dxf.center)))
        if kind == "INSERT" and layer not in opening_kind and layer not in ignored and (
            rec := _recognise(doc, e, k, rec_cache, settings)
        ):  # a door/window/stair symbol on any other layer (26a): mapped or reported, never dropped
            symbols.setdefault((e.dxf.name, e.dxf.layer, rec), []).append(e)
            continue
        if layer in opening_kind:  # ADR-002 §2
            if kind == "INSERT":
                # a block: its footprint (bounding box of the geometry, swing arcs left out) is the marker
                # when it is a rectangle; anything else is reported and not placed (source = block)
                rect = _block_rect(e, mm, settings)
                if rect is None:
                    issues.append(
                        Issue(
                            code="unsupported_opening_block",
                            severity="warning",
                            message=f"INSERT {e.dxf.handle} (block {e.dxf.name}) on "
                            f"{e.dxf.layer}: the block has no rectangular footprint (a flat leaf "
                            "line, a rotation that is not a quarter turn or no geometry), so no "
                            "opening was made from it; draw a closed rectangular LWPOLYLINE "
                            "marker filling the wall gap",
                            sources=[_ref(e)],
                        )
                    )
                else:
                    markers.append(Marker(opening_kind[layer], _ref(e), rect))
                    block_markers.setdefault(e.dxf.name, []).append(_ref(e))
            elif kind == "LWPOLYLINE" and _is_closed(e, settings.tolerance_mm):
                pts = [mm(p) for p in _wcs_xy(e)]
                if math.dist(pts[0], pts[-1]) <= settings.tolerance_mm:
                    pts.pop()  # closed by repeating the first vertex
                plain = not _extrusion_issue(e, settings) and not any(b for *_, b in e.get_points("xyb"))
                rect = marker_rect(pts, settings.tolerance_mm) if plain else None
                quad = (marker_quad(pts, settings.diagonal_tol_mm)
                        if plain and rect is None and settings.diagonal_walls else None)
                if quad is not None:  # a rectangle turned to a diagonal wall
                    markers.append(Marker(opening_kind[layer], _ref(e), _bbox(quad), quad=quad))
                elif rect is None:
                    issues.append(
                        Issue(
                            code="invalid_opening_marker",
                            severity="blocking",
                            message=f"closed LWPOLYLINE {e.dxf.handle} on "
                            f"{e.dxf.layer} is not an opening marker: needs exactly "
                            "4 distinct vertices, axis-aligned edges, no bulges, "
                            "extrusion parallel to Z",
                            sources=[_ref(e)],
                        )
                    )
                else:
                    markers.append(Marker(opening_kind[layer], _ref(e), rect))
            else:
                decorative.setdefault(e.dxf.layer, []).append(e)
                if kind == "ARC" and layer in settings.door_layers:
                    swings.append(e)
            continue
        if layer in ignored:  # the user's explicit choice; still reported below
            user_ignored.setdefault(e.dxf.layer, []).append(e)
            continue
        if kind in ("TEXT", "MTEXT") and not any(
            fnmatchcase(layer, p) for p in settings.non_floor_layer_patterns
        ):
            text = (e.dxf.text if kind == "TEXT" else e.plain_text()).strip()
            if text:
                at = e.ocs().to_wcs(e.dxf.insert) if kind == "TEXT" else e.dxf.insert
                labels.append(Label(text, mm(at), _ref(e)))
        floor_layer_seen |= layer in floor_layers
        if layer not in wall_layers | floor_layers | column_layers | balcony_layers | stair_layers | ramp_layers | settings.roof_layers:
            unmapped.setdefault(e.dxf.layer, []).append(e)
            continue
        if layer in wall_layers and kind == "LINE":
            segments.append(
                Segment(e.dxf.handle, e.dxf.layer, mm(e.dxf.start), mm(e.dxf.end))
            )
        elif kind == "LWPOLYLINE" and (bad := _extrusion_issue(e, settings)):
            issues.append(bad)
        elif kind == "LWPOLYLINE" and any(b for *_, b in e.get_points("xyb")):
            issues.append(_arc_issue(e))
        elif layer in wall_layers and kind == "LWPOLYLINE":
            pts = [mm(p) for p in _wcs_xy(e)]
            ring = pts + pts[:1] if e.closed else pts
            segments += [
                Segment(e.dxf.handle, e.dxf.layer, a, b) for a, b in pairwise(ring)
            ]
        elif layer in floor_layers and kind == "LWPOLYLINE":
            pts = [mm(p) for p in _wcs_xy(e)]
            if len(pts) > 3 and pts[0] == pts[-1]:
                pts.pop()  # closed by repeating the first point
            elif not e.closed:
                pts = []
            if len(pts) < 3:
                issues.append(
                    Issue(
                        code="open_floor_boundary",
                        severity="warning",
                        message=f"floor polyline {e.dxf.handle} is not a "
                        "closed polygon, ignored",
                        sources=[_ref(e)],
                    )
                )
                continue
            if bad := floor_issue(pts, _ref(e), settings):
                issues.append(bad)
                continue
            boundaries.append(
                FloorBoundary(
                    id=f"fb-{len(boundaries) + 1:03d}", polygon=pts, sources=[_ref(e)]
                )
            )
        elif layer in stair_layers | ramp_layers and kind == "LINE":
            arrows.append(Arrow("stair" if layer in stair_layers else "ramp", _ref(e),
                                mm(e.dxf.start), mm(e.dxf.end)))
        elif layer in stair_layers | ramp_layers and kind == "LWPOLYLINE":
            pts = [mm(p) for p in _wcs_xy(e)]
            closed = _is_closed(e, settings.tolerance_mm)
            if len(pts) > 1 and math.dist(pts[0], pts[-1]) <= settings.tolerance_mm:
                pts.pop()
            rect = marker_rect(pts, settings.tolerance_mm) if closed else None
            what = "stair" if layer in stair_layers else "ramp"
            if rect is None:
                issues.append(
                    Issue(
                        code=f"invalid_{what}",
                        severity="warning",
                        message=f"{what} polyline {e.dxf.handle} is not a closed axis-aligned "
                        f"rectangle (4 vertices); no {what} built from it",
                        sources=[_ref(e)],
                    )
                )
            else:
                outlines.append(Outline(what, _ref(e), rect))
        elif layer in settings.roof_layers and kind == "LWPOLYLINE":
            pts = [mm(p) for p in _wcs_xy(e)]
            if len(pts) > 3 and pts[0] == pts[-1]:
                pts.pop()
            elif not e.closed:
                pts = []
            if len(pts) < 3 or Polygon(pts).area <= settings.tolerance_mm or not Polygon(pts).is_valid:
                issues.append(
                    Issue(
                        code="invalid_roof",
                        severity="warning",
                        message=f"roof polyline {e.dxf.handle} is not a closed, valid polygon "
                        "with area; no roof built from it",
                        sources=[_ref(e)],
                    )
                )
            else:
                roof_polys.append((_ref(e), pts))
        elif layer in balcony_layers and kind == "LWPOLYLINE":
            pts = [mm(p) for p in _wcs_xy(e)]
            if len(pts) > 3 and pts[0] == pts[-1]:
                pts.pop()
            elif not e.closed:
                pts = []
            # tolerance_mm doubles as the positive-area threshold in mm2 (see Settings)
            if len(pts) < 3 or Polygon(pts).area <= settings.tolerance_mm or not Polygon(pts).is_valid:
                issues.append(
                    Issue(
                        code="invalid_balcony",
                        severity="warning",
                        message=f"balcony polyline {e.dxf.handle} is not a closed, valid "
                        "polygon with area; no balcony built from it",
                        sources=[_ref(e)],
                    )
                )
            else:
                balc.append((_ref(e), pts))
        elif layer in column_layers and kind == "CIRCLE" and not (bad := _extrusion_issue(e, settings)):
            cols.append((_ref(e), "circle", mm(e.ocs().to_wcs(e.dxf.center)), e.dxf.radius * k))
        elif layer in column_layers and kind == "LWPOLYLINE":
            pts = [mm(p) for p in _wcs_xy(e)]
            closed = _is_closed(e, settings.tolerance_mm)
            if len(pts) > 1 and math.dist(pts[0], pts[-1]) <= settings.tolerance_mm:
                pts.pop()
            rect = marker_rect(pts, settings.tolerance_mm) if closed else None
            if rect is None:
                issues.append(
                    Issue(
                        code="invalid_column",
                        severity="warning",
                        message=f"column polyline {e.dxf.handle} is not a closed axis-aligned "
                        "rectangle (4 vertices); no column built from it. Circles are also read",
                        sources=[_ref(e)],
                    )
                )
            else:
                cols.append((_ref(e), "rect", rect))
        else:
            if kind == "CIRCLE" and layer in column_layers:
                issues.append(bad)  # tilted circle: reported, not placed
                continue
            issues.append(
                Issue(
                    code="unsupported_entity",
                    severity="warning",
                    message=f"{kind} {e.dxf.handle} on {e.dxf.layer} "
                    "unsupported in MVP-0, ignored",
                    sources=[_ref(e)],
                )
            )

    issues += dimension_check(
        (e for e in doc.modelspace() if not scope or e.dxf.handle in scope.handles), k, settings)
    for (bname, blayer, rec), ents in symbols.items():
        refs = [_ref(e) for e in ents]
        if rec.confident:
            placed_refs: list[SourceRef] = []
            for e in ents:
                rect = _block_rect(e, mm, settings)
                if rec.kind == "stair" and rect:
                    outlines.append(Outline("stair", _ref(e), rect))
                    placed_refs.append(_ref(e))
                elif rec.kind in ("door", "window") and rect:
                    markers.append(Marker(rec.kind, _ref(e), rect))
                    block_markers.setdefault(e.dxf.name, []).append(_ref(e))
                    placed_refs.append(_ref(e))
            conf = "high (geometry and name agree)" if rec.name else "medium (geometry only, the name says nothing)"
            placed = len(placed_refs)
            how = (f"{placed} mapped from the block's bounding box (source = block)" if placed else
                   "none placed as a marker (no rectangular footprint)" + (
                       "; the opening comes from the wall gap it sits in, if any" if rec.kind == "door" else ""))
            issues.append(Issue(
                code="block_symbol_recognised", severity="warning",
                message=f"{len(ents)} INSERT(s) of block {bname!r} on {blayer} recognised as {rec.kind}, "
                f"confidence {conf}; {rec.why}; {how}. Check them; map the layer to override",
                sources=refs[:ref_cap]))
            if not rec.name:  # placed on geometry alone: one note per element, with a way to confirm or remove it
                issues += [Issue(
                    code="block_element_inferred", severity="warning",
                    message=f"{rec.kind} from block {bname!r} ({r.entity_handle}) was inferred from block geometry "
                    f"alone, confidence medium (the block name says nothing); confirm it or remove it",
                    sources=[r],
                    suggestions=[Suggestion(kind="confirm_inferred", value=rec.kind,
                                            label=f"confirm the {rec.kind}, or delete it in the plan editor")])
                    for r in placed_refs]
        else:
            cands = rec.candidates
            issues.append(Issue(
                code="block_symbol_ambiguous", severity="warning",
                message=f"{len(ents)} INSERT(s) of block {bname!r} on {blayer} may be a "
                f"{' or '.join(cands)} ({rec.why}) but this is not certain enough to use; nothing was "
                "made from them. Confirm by mapping their layer",
                sources=refs[:ref_cap],
                suggestions=[Suggestion(kind="layer_role", value=c,
                                        label=f"map layer {blayer} to {c} under Layer conventions") for c in cands]))
    for name, ents in unmapped.items():
        counts = Counter(e.dxftype() for e in ents)
        listed = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        if counts.keys() & {"TEXT", "MTEXT"}:
            listed += " (TEXT/MTEXT inside a closed room still name it)"
        more = f"; first {ref_cap} of {len(ents)} listed" if len(ents) > ref_cap else ""
        hints = ""
        if hint := layer_hint(name, settings):  # a suggestion from the name, never applied
            hints += f"; suggestion (not applied): {hint}"
        lines = [Segment(e.dxf.handle, e.dxf.layer, mm(e.dxf.start), mm(e.dxf.end)) for e in ents if e.dxftype() == "LINE"]
        if 0 < len(lines) <= settings.max_wall_segments and (pairs := len(pair_walls(lines, settings)[0])):
            hints += (f"; its lines hold {pairs} parallel line pair(s) at wall-like distances: if it holds "
                      "walls, map it to wall to include them (not applied)")
        issues.append(
            Issue(
                code="unmapped_layer",
                severity="warning",
                message=f"layer {name} is not a mapped layer ("
                f"{', '.join(sorted(wall_layers))}, {settings.floor_label}); ignored {listed}{more}{hints}",
                sources=[_ref(e) for e in ents[:ref_cap]],
                suggestions=[Suggestion(kind="layer_role", value=role.split(" or ")[0],
                                        label=f"map layer {name} to {role} under Layer conventions")]
                if (role := layer_hint_role(name, settings)) else [],
            )
        )
    for name, ents in user_ignored.items():
        issues.append(
            Issue(
                code="layer_ignored_by_user",
                severity="warning",
                message=f"layer {name} was mapped to ignore in the project conventions; "
                f"{len(ents)} entities not read",
                sources=[_ref(e) for e in ents[:ref_cap]],
            )
        )
    for name, ents in decorative.items():
        counts = Counter(e.dxftype() for e in ents)
        listed = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        more = f"; first {ref_cap} of {len(ents)} listed" if len(ents) > ref_cap else ""
        issues.append(
            Issue(
                code="opening_symbol_ignored",
                severity="warning",
                message=f"opening layer {name}: ignored decorative {listed} "
                f"(swings, leaves, glass, tags are never geometry){more}",
                sources=[_ref(e) for e in ents[:ref_cap]],
            )
        )
    edit_ids = {e.id for e in edits}
    thickness_edits = modified_thickness(edits)
    if edits:  # before openings are resolved, so everything downstream re-derives from the edited lines
        segments, markers, edit_issues = apply_geometry_edits(segments, markers, edits, settings)
        issues += edit_issues
    segments, cut_issues = cut_walls_at_markers(segments, [m for m in markers if m.quad is None], settings)
    issues += cut_issues
    segments, turned_cut = cut_walls_at_turned_markers(segments, markers, settings)
    issues += turned_cut
    segments, heal_issues = heal_gaps(segments, markers, settings)
    issues += heal_issues
    res = resolve_openings(segments, markers, settings, tuple(arc_centres))
    paired, pieces = res.walls, res.junctions
    for e in swings:
        centre = mm(e.ocs().to_wcs(e.dxf.center))
        if not on_marker_boundary(centre, [*markers, *(o.marker for o in res.openings if o.marker.inferred)], settings.tolerance_mm):
            issues.append(
                Issue(
                    code="orphan_door_swing",
                    severity="warning",
                    message=f"door-layer ARC {e.dxf.handle} centred at "
                    f"({centre[0]:g}, {centre[1]:g}) is not on any opening marker; "
                    "possible unmarked door",
                    sources=[_ref(e)],
                )
            )

    from_block = {r.entity_handle for refs in block_markers.values() for r in refs}
    for name, refs in block_markers.items():
        issues.append(
            Issue(
                code="opening_from_block",
                severity="warning",
                message=f"{len(refs)} opening(s) read from the bounding box of block {name!r} "
                "(source = block, not a drawn marker); check the sizes",
                sources=refs[:ref_cap],
            )
        )
    for i in res.issues:  # a block that does not fit its wall gap is not placed: reported, not blocking
        if i.severity == "blocking" and i.sources and i.sources[0].entity_handle in from_block:
            i = i.model_copy(update={
                "severity": "warning",
                "message": f"{i.message} (the marker is a block's bounding box: no opening made from it)"})
        issues.append(i)
    roles, role_issues = resolve_roles(paired, pieces, settings)
    if segments:  # the extent of every wall line, so a drawing whose walls could not be paired is checked too
        xs = [v for s in segments for v in (s.start[0], s.end[0])]
        ys = [v for s in segments for v in (s.start[1], s.end[1])]
        longest, lo, hi = max(max(xs) - min(xs), max(ys) - min(ys)), *settings.plausible_footprint_mm
        if not lo <= longest <= hi:
            where = f"header $INSUNITS={insunits} ({_unit_label(insunits)})" if insunits else f"--units {user_units}"
            issues.append(
                Issue(
                    code="units_implausible",
                    severity="warning",
                    message=f"the wall lines span {longest:g} mm at their longest, outside the plausible "
                    f"{lo:g}-{hi:g} mm for a building plan, using {where}. The drawing may be in other "
                    "units; nothing was changed. If so, choose the real units (override the header) "
                    "and generate again",
                )
            )
    if not paired and blank:  # a floor made from an image to trace over: empty until the user draws walls
        issues.append(Issue(code="trace_floor_empty", severity="warning",
                            message="nothing is traced on this floor yet: draw the walls over the underlay in the plan editor"))
    elif not paired:
        issues += _no_plan_geometry(doc, settings)
        issues.append(
            Issue(
                code="no_walls",
                severity="blocking",
                message=f"no paired wall lines found on {settings.wall_label}",
                # every usable segment is unpaired here; polyline pieces share a ref
                sources=list(dict.fromkeys(s.ref for s in res.segments)),
            )
        )

    height = None
    if wall_height is not None:
        height = Measured(value=wall_height, source="user_provided")
    elif paired and preset:
        wall_height = preset.wall_height
        height = Measured(value=wall_height, source="defaulted")
        issues.append(
            Issue(
                code="wall_height_defaulted",
                severity="warning",
                message=f"Wall height assumed {wall_height:g} mm ({building_type} default); "
                "not in the DXF",
            )
        )
    elif paired:
        issues.append(
            Issue(
                code="wall_height_missing",
                severity="blocking",
                message="DXF has no wall height; supply --wall-height (mm)",
            )
        )
    # A ceiling above the walls leaves a gap (a roof at the wall tops with the ceiling, and a stair to it,
    # hidden above it). An ASSUMED wall height (the preset's) is raised to the ceiling, so the model stays
    # whole, and the issue below says so. A wall height the user gave is a known measurement and is never
    # altered: it stays, and the same issue warns about the gap instead.
    ceil_target = ceiling_height if ceiling_height is not None else (
        preset.ceiling_height if (paired and preset) else None)
    ceiling_over_walls = None  # (wall height as it was, raised?)
    if height is not None and ceil_target is not None and ceil_target > height.value + settings.tolerance_mm:
        raised = height.source == "defaulted"
        ceiling_over_walls = (height.value, raised)
        if raised:
            for i, it in enumerate(issues):  # the "assumed" note must report the value actually used
                if it.code == "wall_height_defaulted":
                    issues[i] = Issue(
                        code="wall_height_defaulted", severity="warning",
                        message=f"Wall height assumed {height.value:g} mm ({building_type} default) and "
                        f"raised to {ceil_target:g} mm to meet the ceiling; not in the DXF")
            wall_height = ceil_target
            height = Measured(value=ceil_target, source="inferred")
    # a user-given lintel (opening head) height sizes openings that have no height of their own;
    # the preset's nominal heights stay when the lintel is only the assumed default
    door_h, window_h = door_height, window_height
    if (lintel := given.get("lintel_height")) is not None:
        door_h = lintel if door_h is None else door_h
        sill = window_sill if window_sill is not None else settings.default_window_sill_mm
        if window_h is None and lintel > sill:
            window_h = lintel - sill
        elif window_h is None and any(f.kind == "window" for f in res.openings):
            issues.append(
                Issue(
                    code="lintel_below_sill",
                    severity="warning",
                    message=f"lintel height {lintel:g} mm is not above the window sill "
                    f"{sill:g} mm; window heights not derived from it",
                )
            )
    openings, opening_issues = build_openings(
        res.openings,
        wall_height,
        {"door": (door_h, None), "window": (window_h, window_sill)},
        from_user,
        settings,
        opening_dimensions(edits),
    )
    issues += opening_issues
    arcs = []
    for e in swings:  # extrusion-aware: the arc's midpoint and centre in world coordinates
        t = e.construction_tool()
        span = (t.end_angle - t.start_angle) % 360 or 360
        a = math.radians(t.start_angle + span / 2)
        mid = e.ocs().to_wcs((e.dxf.center.x + e.dxf.radius * math.cos(a),
                              e.dxf.center.y + e.dxf.radius * math.sin(a), e.dxf.center.z))
        arcs.append(SwingArc(mm(e.ocs().to_wcs(e.dxf.center)), mm(mid), _ref(e)))
    swing_of, swing_issues = door_swings(res.openings, arcs, settings)
    issues += swing_issues
    openings = [
        o.model_copy(update={"swing": swing_of[o.sources[0].entity_handle]})
        if o.sources[0].entity_handle in swing_of else o
        for o in openings
    ]

    walls = [
        Wall(
            id=w.id,
            centreline=LineGeometry(start=w.start, end=w.end),
            thickness=Measured(
                value=w.thickness,
                source="user_modified" if any(s.handle in thickness_edits for s in w.sources)
                else "user_provided" if from_user else "source_extracted",
            ),
            height=height,
            sources=[edit_ref(s.ref, edit_ids) for s in w.sources],
            role=(roles[w.id] or (None, None))[0],
            role_source=(roles[w.id] or (None, None))[1],
        )
        for w in paired
    ]
    junctions = [
        Junction(id=j.id, polygon=j.polygon, wall_ids=j.wall_ids) for j in pieces
    ]
    if floor_elevation is not None and elevation_assumed:
        issues.append(
            Issue(code="elevation_defaulted", severity="warning", message=elevation_assumed)
        )
        elevation = Measured(value=floor_elevation, source="defaulted")
    elif floor_elevation is None:
        issues.append(
            Issue(
                code="elevation_defaulted",
                severity="warning",
                message="floor elevation assumed 0 mm; DXF plan carries no elevation",
            )
        )
        elevation = Measured(value=0, source="defaulted")
    else:
        elevation = Measured(value=floor_elevation, source="user_provided")
    issues += role_issues
    if scope:
        issues += scope.notes
    found, room_issues = find_rooms(paired, pieces, labels, settings) if paired else ([], [])
    if paired and not boundaries and not floor_layer_seen and settings.infer_floor_boundary:
        inferred, note = _infer_boundaries(paired, pieces, found, settings)
        boundaries += inferred
        issues.append(note)
    # Floor convention (model.py): `elevation` is the underside of the slab, the finished floor is the
    # slab thickness higher. Wall, ceiling and roof heights are measured from the finished floor.
    slab_param = given.get("slab_thickness", preset.slab_thickness if preset else None)
    floor_t = slab_param if (boundaries and slab_param) else 0.0
    ceil_h = ceilings = None
    ceil_src = "user_provided"
    if ceiling_height is None and paired and preset:
        ceiling_height, ceil_src = preset.ceiling_height, "defaulted"
        issues.append(
            Issue(
                code="ceiling_height_defaulted",
                severity="warning",
                message=f"Ceiling height assumed {ceiling_height:g} mm ({building_type} "
                "default); not in the DXF",
            )
        )
    if ceiling_height is not None:
        ceil_h = Measured(value=ceiling_height, source=ceil_src)
        # derived sum, so "inferred" (not the user's own number); the floor
        # elevation it builds on is still reported by elevation_defaulted
        top = Measured(value=elevation.value + floor_t + ceiling_height, source="inferred")
        ceilings = [
            Ceiling(
                id=b.id.replace("fb-", "ceiling-", 1),
                polygon=b.polygon,
                elevation=top,
                height=ceil_h,
                sources=b.sources,
            )
            for b in boundaries
        ]
        if not boundaries:
            issues.append(
                Issue(
                    code="ceiling_not_built",
                    severity="warning",
                    message="ceiling height given but no floor boundary on "
                    f"{settings.floor_label}; no ceiling built",
                )
            )
        if (
            wall_height is not None
            and wall_height > ceiling_height + settings.tolerance_mm
            and ("wall_height" in given or "ceiling_height" in given)  # not just the preset's own pair
        ):
            issues.append(
                Issue(
                    code="walls_above_ceiling",
                    severity="warning",
                    message=f"wall height {wall_height:g} mm exceeds ceiling height {ceiling_height:g} mm: "
                    "the storey is the ceiling height, so stairs and the next floor follow the ceiling "
                    "and the walls rise above it (roof sits on the walls); set both to move the storey",
                )
            )
        if ceiling_over_walls is not None:
            was, raised = ceiling_over_walls
            issues.append(
                Issue(
                    code="ceiling_above_walls",
                    severity="warning",
                    message=f"ceiling height {ceiling_height:g} mm exceeds wall height {was:g} mm; "
                    + ("the assumed walls were raised to the ceiling" if raised else
                       "the wall height you gave is kept, so there is a gap above the walls"),
                )
            )
    elif paired:
        issues.append(
            Issue(
                code="ceiling_height_missing",
                severity="blocking",
                message="DXF has no ceiling height; supply --ceiling-height (mm)",
            )
        )
    if not paired and labels:
        issues.append(Issue(
            code="rooms_not_built", severity="warning",
            message=f"no walls, so no rooms were built; {len(labels)} text label(s) not used",
            sources=[x.ref for x in labels[: settings.unmapped_ref_cap]],
        ))
    issues += room_issues
    rooms = [
        Room(
            id=p.id, name=p.name, name_source="source_extracted" if p.name_from_label else "defaulted",
            polygon=p.polygon, holes=p.holes, area=Area(value=p.area, source="inferred"),
            label_sources=[x.ref for x in p.labels],
        )
        for p in found
    ]
    rooms, rename_issues = apply_room_edits(rooms, edits)
    issues += rename_issues
    columns = []
    for n, c in enumerate(sorted(cols, key=lambda c: (c[2][1], c[2][0])), 1):  # y, then x
        ref = c[0]
        if c[1] == "rect":
            x0, y0, x1, y1 = c[2]
            columns.append(Column(
                id=f"col-{n:03d}", shape="rect", polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                height=ceil_h, sources=[ref]))
        else:
            columns.append(Column(
                id=f"col-{n:03d}", shape="circle", centre=c[2],
                radius=Measured(value=c[3], source="user_provided" if from_user else "source_extracted"),
                height=ceil_h, sources=[ref]))
    if columns and ceil_h is None:
        issues.append(Issue(
            code="column_height_missing", severity="warning",
            message=f"{len(columns)} column(s) have no height (no ceiling height, e.g. no walls "
            "to default it from); recorded without one and not extruded",
            sources=[c.sources[0] for c in columns[: settings.unmapped_ref_cap]]))
    stairs, ramps = [], []
    if outlines or arrows:
        flights, flight_issues = find_flights(outlines, arrows, settings)
        issues += flight_issues
        slab_t = given.get("slab_thickness", preset.slab_thickness if preset else None)
        slab_p = "user_provided" if "slab_thickness" in given else "defaulted"
        rise_p = given.get("stair_rise", preset.stair_rise if preset else None)
        run_p = given.get("stair_run", preset.stair_run if preset else None)
        total = None
        if ceil_h is not None and slab_t is not None:  # derived sum, so inferred
            # the storey is the CEILING height (vertical convention, model.py): the next floor's slab
            # starts at this ceiling plane, so the stair rises ceiling + slab to the next finished floor
            total = Measured(value=ceil_h.value + slab_t, source="inferred")
        elif flights:
            issues.append(Issue(
                code="stair_rise_unknown", severity="warning",
                message="total rise (ceiling height + slab thickness) is unknown "
                f"({'no ceiling height' if ceil_h is None else 'no slab thickness'}); no steps or "
                "ramp slope built", sources=[f.ref for f in flights[: settings.unmapped_ref_cap]]))
        for f in flights:
            poly = [(f.rect[0], f.rect[1]), (f.rect[2], f.rect[1]), (f.rect[2], f.rect[3]),
                    (f.rect[0], f.rect[3])]
            srcs = [f.ref, *([f.arrow] if f.arrow else [])]
            if f.kind == "ramp":
                ok = total is not None and f.direction is not None
                slope = total.value / f.length if ok else None
                if ok and slope > settings.ramp_max_slope:
                    issues.append(Issue(
                        code="ramp_slope_steep", severity="warning",
                        message=f"{f.id}: rises {total.value:g} mm (ceiling + slab, a full floor) "
                        f"over {f.length:g} mm = 1:{1 / slope:.1f}, steeper than the 1:"
                        f"{1 / settings.ramp_max_slope:g} limit; built as drawn",
                        sources=srcs))
                ramps.append(Ramp(
                    id=f.id, polygon=poly, direction=f.direction,
                    rise=total if ok else None,
                    thickness=Measured(value=slab_t, source=slab_p) if ok and slab_t else None,
                    slope=slope, sources=srcs))
                continue
            kw = {}
            if total is not None and f.direction is not None and not rise_p:
                issues.append(Issue(
                    code="stair_rise_param_missing", severity="warning",
                    message=f"{f.id}: no stair rise parameter (choose a building type or set "
                    "the parameter), so the steps cannot be counted; no steps built",
                    sources=srcs))
            if total is not None and f.direction is not None and rise_p:
                n = round(total.value / rise_p)
                if n < 2:
                    issues.append(Issue(
                        code="stair_too_low", severity="warning",
                        message=f"{f.id}: total rise {total.value:g} mm is under 1.5 risers of "
                        f"{rise_p:g} mm; no steps built", sources=srcs))
                else:
                    going = f.length / (n - 1)
                    kw = {"riser_count": n,
                          "riser_height": Measured(value=total.value / n, source="inferred"),
                          "tread_depth": Measured(value=going, source="inferred")}
                    if run_p and abs(going - run_p) > settings.stair_run_tolerance * run_p:
                        issues.append(Issue(
                            code="stair_run_mismatch", severity="warning",
                            message=f"{f.id}: the drawn length {f.length:g} mm over {n - 1} treads "
                            f"gives {going:g} mm treads, not the {run_p:g} mm stair run parameter "
                            "(more than the tolerance); built as drawn", sources=srcs))
            stairs.append(Stair(
                id=f.id, polygon=poly, direction=f.direction, total_rise=total,
                rise_param=None if rise_p is None else Measured(
                    value=rise_p, source="user_provided" if "stair_rise" in given else "defaulted"),
                run_param=None if run_p is None else Measured(
                    value=run_p, source="user_provided" if "stair_run" in given else "defaulted"),
                sources=srcs, **kw))
    roofs = []
    if not roof and roof_polys:
        issues.append(Issue(
            code="roof_not_top_floor", severity="warning",
            message=f"{len(roof_polys)} roof-plan outline(s) on a floor that is not the top of its "
            "project; no roof built here",
            sources=[ref for ref, _ in roof_polys[: settings.unmapped_ref_cap]]))
    if roof and not paired and roof_polys:
        issues.append(Issue(
            code="roof_without_walls", severity="warning",
            message=f"{len(roof_polys)} roof-plan outline(s) but no walls, so no roof was built "
            "(its base elevation comes from the wall height)",
            sources=[ref for ref, _ in roof_polys[: settings.unmapped_ref_cap]]))
    if roof and paired:
        req_t = given.get("roof_type", preset.roof_type if preset else None)
        t_src = "user_provided" if "roof_type" in given else "defaulted"
        pitch_v = given.get("roof_pitch", preset.roof_pitch if preset else None)
        p_src = "user_provided" if "roof_pitch" in given else "defaulted"
        if req_t is None:
            issues.append(Issue(
                code="roof_type_unknown", severity="warning",
                message="no roof type (choose a building type or set the parameter); no roof built"))
        else:
            outs = (
                [RoofOutline(pts, "roof_layer", [ref]) for ref, pts in roof_polys] if roof_polys
                else wall_outlines([w.rect() for w in paired] + [Polygon(j.polygon) for j in pieces]
                                   + [Polygon(b.polygon) for b in boundaries], settings)
            )
            plans, roof_issues = plan_roofs(outs, req_t, pitch_v, settings)
            issues += roof_issues
            base = None if height is None else Measured(
                value=elevation.value + floor_t + height.value, source="inferred")
            if plans and base is None:
                issues.append(Issue(
                    code="roof_base_unknown", severity="warning",
                    message="no wall height, so the roof has no base elevation; roof recorded "
                    "but not built"))
            for pl in plans:
                kw: dict = {}
                if pl.kind == "flat":
                    kw["thickness"] = Measured(value=settings.roof_thickness_mm, source="defaulted")
                else:
                    x0, y0, x1, y1 = pl.rect
                    # a drawn roof-plan outline is the roof edge already; only the wall outline
                    # gets the nominal eave overhang
                    drawn = pl.outline.source == "roof_layer"
                    o = 0.0 if drawn else settings.roof_overhang_mm
                    short = min(x1 - x0, y1 - y0) + 2 * o
                    kw.update(
                        overhang=Measured(value=o, source="source_extracted" if drawn else "defaulted"),
                        pitch=Param(value=pitch_v, unit="deg", source=p_src),
                        ridge_axis=pl.ridge_axis,
                        ridge_height=Measured(value=ridge_height(short, pitch_v), source="inferred"),
                    )
                roofs.append(Roof(
                    id=pl.id, kind=pl.kind, requested=pl.requested, polygon=pl.outline.polygon,
                    outline_source=pl.outline.source, base_elevation=base,
                    type_param=Param(value=req_t, unit="none", source=t_src),
                    sources=pl.outline.refs, **kw))
            if plans and t_src == "defaulted":
                issues.append(Issue(
                    code="roof_type_defaulted", severity="warning",
                    message=f"Roof type {req_t} assumed ({building_type} default)"
                    + (f" at {pitch_v:g} deg pitch"
                       if any(p.kind != "flat" for p in plans) and p_src == "defaulted" else "")
                    + "; not in the DXF"))
            elif p_src == "defaulted" and any(p.kind != "flat" for p in plans):
                issues.append(Issue(
                    code="roof_pitch_defaulted", severity="warning",
                    message=f"Roof pitch assumed {pitch_v:g} deg ({building_type} default); "
                    "not in the DXF"))
    balconies = []
    if balc:
        pieces_b, balc_issues = find_balconies(
            balc, paired, pieces, [p.polygon for p in found], settings)
        issues += balc_issues
        railing_h = given.get("railing_height", preset.railing_height if preset else None)
        rail_src = "user_provided" if "railing_height" in given else "defaulted"
        slab_b = given.get("slab_thickness", preset.slab_thickness if preset else None)
        slab_src = "user_provided" if "slab_thickness" in given else "defaulted"
        if railing_h is not None and rail_src == "defaulted":
            issues.append(Issue(
                code="railing_height_defaulted", severity="warning",
                message=f"Balcony railing height assumed {railing_h:g} mm ({building_type} "
                "default); not in the DXF", sources=[p.ref for p in pieces_b]))
        if railing_h is None:
            issues.append(Issue(
                code="railing_height_missing", severity="warning",
                message="no railing height (choose a building type or set the parameter); "
                "balcony railings not built", sources=[p.ref for p in pieces_b]))
        for p in pieces_b:
            balconies.append(Balcony(
                id=p.id, polygon=p.polygon,
                thickness=None if slab_b is None else Measured(value=slab_b, source=slab_src),
                railing_height=None if railing_h is None else Measured(value=railing_h, source=rail_src),
                railing_thickness=None if railing_h is None else Measured(
                    value=settings.railing_thickness_mm, source="defaulted"),
                railings=p.railings if railing_h is not None else [],
                sources=[p.ref]))
    slabs = []
    if boundaries and slab_param:
        slab_src = "user_provided" if "slab_thickness" in given else "defaulted"
        # one slab per floor boundary, filling the room between the structural base and the finished
        # floor; the walls start at the base too (they run down beside the slab), so nothing floats
        slabs = [
            Slab(
                id=b.id.replace("fb-", "slab-", 1),
                boundary_id=b.id,
                boundary_ids=[b.id],
                polygon=b.polygon,
                thickness=Measured(value=slab_param, source=slab_src),
                sources=b.sources,
            )
            for b in boundaries
        ]
    if paired:  # spaces the walls enclose that no floor outline covers get no slab and no walking surface
        floors_union = unary_union([Polygon(b.polygon) for b in boundaries]) if boundaries else Polygon()
        bare = [
            h for o in wall_outlines([w.rect() for w in paired] + [Polygon(j.polygon) for j in pieces], settings)
            for h in o.holes if Polygon(h).difference(floors_union).area > 1.0  # mm2: below that is float noise
        ]
        if bare:
            issues.append(Issue(
                code="slab_hole_without_floor", severity="warning",
                message=f"{len(bare)} enclosed space(s) have no closed polyline on {settings.floor_label}, so "
                "they get no floor slab and no walking surface (a courtyard is fine; a room needs its outline)",
                sources=[s for b in boundaries for s in b.sources[:1]][: settings.unmapped_ref_cap]))
    # one report for the default, whichever of slabs, balconies, stairs or ramps use it
    slab_default = given.get("slab_thickness") is None and preset is not None
    if slab_default and (
        slabs or balconies or any(s.total_rise for s in stairs) or any(r.thickness for r in ramps)
    ):
        issues.append(
            Issue(
                code="slab_thickness_defaulted",
                severity="warning",
                message=f"Slab thickness assumed {preset.slab_thickness:g} mm ({building_type} "
                "default); not in the DXF",
            )
        )
    parameters = {
        name: Param(value=given[name], unit=unit, source="user_provided")
        if name in given
        else Param(value=getattr(preset, name), unit=unit, source="defaulted")
        for name, unit in PARAMS.items()
        if name in given or preset
    }
    floor = Floor(
        id=floor_id,
        name=floor_name,
        elevation=elevation,
        ceiling_height=ceil_h,
        ceilings=ceilings or [],
        slabs=slabs,
        rooms=rooms,
        columns=columns,
        balconies=balconies,
        stairs=stairs,
        ramps=ramps,
        roofs=roofs,
        walls=walls,
        junctions=junctions,
        boundaries=boundaries,
        openings=openings,
        plan_offset=PlanOffset(x=ox, y=oy, source="user_provided") if scope else None,
    )
    return Project(
        **project, buildings=[Building(id="bldg-0", floors=[floor])], issues=issues,
        parameters=parameters,
    )
