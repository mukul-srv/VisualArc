"""DXF -> canonical Project, MVP-0 convention.

Walls = paired parallel LINE/LWPOLYLINE segments on A-WALL; floors = closed
LWPOLYLINE on A-FLOR. Everything is converted to mm via $INSUNITS.
"""

from collections import Counter
from itertools import pairwise
from pathlib import Path

import ezdxf
from ezdxf import units

from api.engine.canonical.model import (
    Building,
    Floor,
    FloorBoundary,
    Issue,
    Junction,
    LineGeometry,
    Measured,
    Project,
    SourceRef,
    Wall,
)
from api.engine.geometry2d.floor import floor_issue
from api.engine.geometry2d.walls import Segment, find_junctions, pair_walls
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
    settings: Settings = DEFAULTS,
) -> Project:
    if wall_height is not None and wall_height <= 0:
        raise ValueError(f"wall height must be > 0 mm, got {wall_height}")
    doc = load_doc(path, settings.max_dxf_bytes if max_bytes is None else max_bytes)
    wall_layer, floor_layer = settings.wall_layer, settings.floor_layer
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

    def mm(p) -> tuple[float, float]:
        return (p[0] * k, p[1] * k)

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
    for e in doc.modelspace():
        layer, kind = e.dxf.layer.upper(), e.dxftype()
        if layer not in (wall_layer, floor_layer):
            unmapped.setdefault(e.dxf.layer, []).append(e)
            continue
        if layer == wall_layer and kind == "LINE":
            segments.append(
                Segment(e.dxf.handle, e.dxf.layer, mm(e.dxf.start), mm(e.dxf.end))
            )
        elif kind == "LWPOLYLINE" and (bad := _extrusion_issue(e, settings)):
            issues.append(bad)
        elif kind == "LWPOLYLINE" and any(b for *_, b in e.get_points("xyb")):
            issues.append(_arc_issue(e))
        elif layer == wall_layer and kind == "LWPOLYLINE":
            pts = [mm(p) for p in _wcs_xy(e)]
            ring = pts + pts[:1] if e.closed else pts
            segments += [
                Segment(e.dxf.handle, e.dxf.layer, a, b) for a, b in pairwise(ring)
            ]
        elif layer == floor_layer and kind == "LWPOLYLINE":
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
        more = f"; first {ref_cap} of {len(ents)} listed" if len(ents) > ref_cap else ""
        issues.append(
            Issue(
                code="unmapped_layer",
                severity="warning",
                message=f"layer {name} is not a mapped layer ({wall_layer}, "
                f"{floor_layer}); ignored {listed}{more}",
                sources=[_ref(e) for e in ents[:ref_cap]],
            )
        )

    paired, pair_issues = pair_walls(segments, settings)
    pieces, junction_issues = find_junctions(segments, paired, settings)
    issues += pair_issues + junction_issues
    if not paired:
        issues.append(
            Issue(
                code="no_walls",
                severity="blocking",
                message=f"no paired wall lines found on {wall_layer}",
                # every usable segment is unpaired here; polyline pieces share a ref
                sources=list(dict.fromkeys(s.ref for s in segments)),
            )
        )

    height = None
    if wall_height is not None:
        height = Measured(value=wall_height, source="user_provided")
    elif paired:
        issues.append(
            Issue(
                code="wall_height_missing",
                severity="blocking",
                message="DXF has no wall height; supply --wall-height (mm)",
            )
        )

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
        )
        for w in paired
    ]
    junctions = [
        Junction(id=j.id, polygon=j.polygon, wall_ids=j.wall_ids) for j in pieces
    ]
    issues.append(
        Issue(
            code="elevation_defaulted",
            severity="warning",
            message="floor elevation assumed 0 mm; DXF plan carries no elevation",
        )
    )
    floor = Floor(
        id="floor-0",
        name="Level 0",
        elevation=Measured(value=0, source="defaulted"),
        walls=walls,
        junctions=junctions,
        boundaries=boundaries,
    )
    return Project(
        **project, buildings=[Building(id="bldg-0", floors=[floor])], issues=issues
    )
