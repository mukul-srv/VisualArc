"""DXF -> canonical Project, MVP-0 convention.

Walls = paired parallel LINE/LWPOLYLINE segments on A-WALL; floors = closed
LWPOLYLINE on A-FLOR; openings = closed rectangular LWPOLYLINE markers on
A-DOOR/A-GLAZ filling wall gaps (ADR-002). Everything is converted to mm via
$INSUNITS.
"""
import math
from collections import Counter
from dataclasses import replace
from fnmatch import fnmatchcase
from itertools import pairwise
from pathlib import Path

import ezdxf
from ezdxf import units

from api.engine.adapters.dxf.split import FloorScope, detect_floors, strip_floor_prefix
from api.engine.canonical.model import (
    Area,
    Building,
    Ceiling,
    Floor,
    FloorBoundary,
    Issue,
    Junction,
    LineGeometry,
    Measured,
    Param,
    PlanOffset,
    Project,
    Room,
    Slab,
    SourceRef,
    Wall,
)
from api.engine.geometry2d.floor import floor_issue
from api.engine.geometry2d.openings import (
    Marker,
    build_openings,
    marker_rect,
    on_marker_boundary,
    resolve_openings,
)
from api.engine.geometry2d.role import resolve_roles
from api.engine.geometry2d.rooms import Label, find_rooms
from api.engine.geometry2d.walls import Segment
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


class InputError(ValueError):
    """Expected bad input (not a DXF, corrupt, too large): report, don't traceback."""


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


def resolve_scale(doc, user_units: str | None = None) -> float | None:
    """Drawing units -> mm, or None when the units are missing, conflicting or
    unsupported (read_dxf reports those as blocking issues)."""
    code = doc.header.get("$INSUNITS", 0)
    user = USER_UNITS[user_units] if user_units else None
    if isinstance(code, bool) or not isinstance(code, int) or (code and user and code != user):
        return None
    try:
        return units.conversion_factor(code or user, units.MM) if code or user else None
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
                               **(params or {})}.items() if v is not None}
    if unknown := set(given) - set(PARAMS):
        raise ValueError(f"unknown parameters {sorted(unknown)}")
    if given.get("slab_thickness", 1) <= 0:
        raise ValueError("slab thickness must be > 0 mm")
    doc = load_doc(path, settings.max_dxf_bytes if max_bytes is None else max_bytes)
    check_complexity(doc, settings)
    wall_layers, floor_layers = settings.wall_layers, settings.floor_layers
    ignored = set(settings.ignore_layers)
    ref_cap = settings.unmapped_ref_cap
    project = {"id": path.stem, "source_file": path.name}

    insunits = doc.header.get("$INSUNITS", 0)
    if isinstance(insunits, bool) or not isinstance(insunits, int):
        return _units_unsupported(project, insunits)
    user_code = USER_UNITS[user_units] if user_units else None
    if user_code and insunits and insunits != user_code:
        return Project(
            **project,
            issues=[
                Issue(
                    code="units_conflict",
                    severity="blocking",
                    message=f"--units {user_units} conflicts with header $INSUNITS="
                    f"{insunits} ({_unit_label(insunits)}); no override, "
                    "fix the drawing or drop --units",
                )
            ],
        )
    if not insunits and not user_code:
        return Project(
            **project,
            issues=[
                Issue(
                    code="units_missing",
                    severity="blocking",
                    message="$INSUNITS is not set; supply --units, refusing to guess",
                )
            ],
        )
    # header agrees with --units: stays source_extracted; only a missing header
    # makes the scale depend on the user
    from_user = not insunits
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

    if scope is None:  # a consolidated file must be split and confirmed first
        split = detect_floors(doc, k, settings)
        if len(split.candidates) > 1:
            keys = ", ".join(c.key for c in split.candidates)
            return Project(
                **project,
                issues=[
                    Issue(
                        code="floor_split_unconfirmed",
                        severity="blocking",
                        message=f"drawing holds {len(split.candidates)} floor candidates "
                        f"({keys}); confirm each floor's name, elevation and offset "
                        "(POST /api/v1/uploads/{id}/split) before generating",
                    ),
                    *split.issues,
                ],
            )

    issues: list[Issue] = []
    if from_user:
        issues.append(
            Issue(
                code="units_user_provided",
                severity="warning",
                message=f"$INSUNITS is not set; scaled to mm using user-supplied "
                f"--units {user_units}",
            )
        )
    segments: list[Segment] = []
    boundaries: list[FloorBoundary] = []
    unmapped: dict[str, list] = {}  # layer -> entities, in drawing order
    opening_kind = {
        **dict.fromkeys(settings.window_layers, "window"),
        **dict.fromkeys(settings.door_layers, "door"),
    }
    user_ignored: dict[str, list] = {}  # layer -> entities the user mapped to "ignore"
    markers: list[Marker] = []
    decorative: dict[str, list] = {}  # opening layer -> ignored symbol entities
    swings = []  # ARCs on the door layer (orphan check)
    labels: list[Label] = []  # TEXT/MTEXT: room-name candidates, placed later
    for e in doc.modelspace():
        if scope and e.dxf.handle not in scope.handles:
            continue
        layer, kind = strip_floor_prefix(e.dxf.layer, settings).upper(), e.dxftype()
        if layer in opening_kind:  # ADR-002 §2
            if kind == "INSERT":
                issues.append(
                    Issue(
                        code="unsupported_opening_block",
                        severity="blocking",
                        message=f"INSERT {e.dxf.handle} (block {e.dxf.name}) on "
                        f"{e.dxf.layer}: opening blocks are not read; draw a closed "
                        "rectangular LWPOLYLINE marker filling the wall gap",
                        sources=[_ref(e)],
                    )
                )
            elif kind == "LWPOLYLINE" and _is_closed(e, settings.tolerance_mm):
                pts = [mm(p) for p in _wcs_xy(e)]
                if math.dist(pts[0], pts[-1]) <= settings.tolerance_mm:
                    pts.pop()  # closed by repeating the first vertex
                rect = (
                    None
                    if _extrusion_issue(e, settings)
                    or any(b for *_, b in e.get_points("xyb"))
                    else marker_rect(pts, settings.tolerance_mm)
                )
                if rect is None:
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
        if layer not in wall_layers and layer not in floor_layers:
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
        else:
            issues.append(
                Issue(
                    code="unsupported_entity",
                    severity="warning",
                    message=f"{kind} {e.dxf.handle} on {e.dxf.layer} "
                    "unsupported in MVP-0, ignored",
                    sources=[_ref(e)],
                )
            )

    for name, ents in unmapped.items():
        counts = Counter(e.dxftype() for e in ents)
        listed = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        if counts.keys() & {"TEXT", "MTEXT"}:
            listed += " (TEXT/MTEXT inside a closed room still name it)"
        more = f"; first {ref_cap} of {len(ents)} listed" if len(ents) > ref_cap else ""
        issues.append(
            Issue(
                code="unmapped_layer",
                severity="warning",
                message=f"layer {name} is not a mapped layer ("
                f"{', '.join(sorted(wall_layers))}, {settings.floor_label}); ignored {listed}{more}",
                sources=[_ref(e) for e in ents[:ref_cap]],
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
    for e in swings:
        centre = mm(e.ocs().to_wcs(e.dxf.center))
        if not on_marker_boundary(centre, markers, settings.tolerance_mm):
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

    res = resolve_openings(segments, markers, settings)
    paired, pieces = res.walls, res.junctions
    issues += res.issues
    roles, role_issues = resolve_roles(paired, pieces, settings)
    if not paired:
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
    openings, opening_issues = build_openings(
        res.openings,
        wall_height,
        {"door": (door_height, None), "window": (window_height, window_sill)},
        from_user,
        settings,
    )
    issues += opening_issues

    walls = [
        Wall(
            id=w.id,
            centreline=LineGeometry(start=w.start, end=w.end),
            thickness=Measured(
                value=w.thickness,
                source="user_provided" if from_user else "source_extracted",
            ),
            height=height,
            sources=[s.ref for s in w.sources],
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
        top = Measured(value=elevation.value + ceiling_height, source="inferred")
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
        if wall_height is not None and ceiling_height > wall_height:
            issues.append(
                Issue(
                    code="ceiling_above_walls",
                    severity="warning",
                    message=f"ceiling height {ceiling_height:g} mm exceeds wall "
                    f"height {wall_height:g} mm; there is a gap above the walls",
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
    found, room_issues = find_rooms(paired, pieces, labels, settings) if paired else ([], [])
    issues += room_issues
    if not paired and labels:
        issues.append(Issue(
            code="rooms_not_built", severity="warning",
            message=f"no walls, so no rooms were built; {len(labels)} text label(s) not used",
            sources=[x.ref for x in labels[: settings.unmapped_ref_cap]],
        ))
    rooms = [
        Room(
            id=p.id, name=p.name, name_source="source_extracted" if p.name_from_label else "defaulted",
            polygon=p.polygon, holes=p.holes, area=Area(value=p.area, source="inferred"),
            label_sources=[x.ref for x in p.labels],
        )
        for p in found
    ]
    slabs = []
    if boundaries and (
        slab_t := given.get("slab_thickness", preset.slab_thickness if preset else None)
    ):
        slab_src = "user_provided" if "slab_thickness" in given else "defaulted"
        if slab_src == "defaulted":
            issues.append(
                Issue(
                    code="slab_thickness_defaulted",
                    severity="warning",
                    message=f"Slab thickness assumed {slab_t:g} mm ({building_type} default); "
                    "not in the DXF",
                )
            )
        slabs = [
            Slab(
                id=b.id.replace("fb-", "slab-", 1),
                boundary_id=b.id,
                polygon=b.polygon,
                thickness=Measured(value=slab_t, source=slab_src),
                sources=b.sources,
            )
            for b in boundaries
        ]
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
