"""DXF -> canonical Project, MVP-0 convention.

Walls = paired parallel LINE/LWPOLYLINE segments on A-WALL; floors = closed
LWPOLYLINE on A-FLOR. Everything is converted to mm via $INSUNITS.
"""

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
from api.engine.geometry2d.walls import Segment, find_junctions, pair_walls

WALL_LAYER, FLOOR_LAYER = "A-WALL", "A-FLOR"


def _ref(e) -> SourceRef:
    return SourceRef(layer=e.dxf.layer, entity_handle=e.dxf.handle)


def _arc_issue(e) -> Issue:
    return Issue(
        code="unsupported_arc",
        severity="warning",
        message=f"{e.dxftype()} {e.dxf.handle} has arc segments; "
        "unsupported in MVP-0, ignored",
        sources=[_ref(e)],
    )


def read_dxf(path: Path, wall_height: float | None = None) -> Project:
    if wall_height is not None and wall_height <= 0:
        raise ValueError(f"wall height must be > 0 mm, got {wall_height}")
    doc = ezdxf.readfile(path)
    project = {"id": path.stem, "source_file": path.name}

    insunits = doc.header.get("$INSUNITS", 0)
    if not insunits:
        return Project(
            **project,
            issues=[
                Issue(
                    code="units_missing",
                    severity="blocking",
                    message="$INSUNITS is not set; units must be supplied, refusing to guess",
                )
            ],
        )
    k = units.conversion_factor(insunits, units.MM)

    def mm(p) -> tuple[float, float]:
        return (p[0] * k, p[1] * k)

    issues: list[Issue] = []
    segments: list[Segment] = []
    boundaries: list[FloorBoundary] = []
    for e in doc.modelspace():
        layer, kind = e.dxf.layer.upper(), e.dxftype()
        if layer not in (WALL_LAYER, FLOOR_LAYER):
            continue
        if layer == WALL_LAYER and kind == "LINE":
            segments.append(
                Segment(e.dxf.handle, e.dxf.layer, mm(e.dxf.start), mm(e.dxf.end))
            )
        elif kind == "LWPOLYLINE" and any(b for *_, b in e.get_points("xyb")):
            issues.append(_arc_issue(e))
        elif layer == WALL_LAYER and kind == "LWPOLYLINE":
            pts = [mm(p) for p in e.get_points("xy")]
            ring = pts + pts[:1] if e.closed else pts
            segments += [
                Segment(e.dxf.handle, e.dxf.layer, a, b) for a, b in pairwise(ring)
            ]
        elif layer == FLOOR_LAYER and kind == "LWPOLYLINE":
            pts = [mm(p) for p in e.get_points("xy")]
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

    paired, pair_issues = pair_walls(segments)
    pieces, junction_issues = find_junctions(segments, paired)
    issues += pair_issues + junction_issues
    if not paired:
        issues.append(
            Issue(
                code="no_walls",
                severity="blocking",
                message=f"no paired wall lines found on {WALL_LAYER}",
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
            thickness=Measured(value=w.thickness, source="source_extracted"),
            height=height,
            sources=[s.ref for s in w.sources],
        )
        for w in paired
    ]
    junctions = [
        Junction(id=j.id, polygon=j.polygon, wall_ids=j.wall_ids) for j in pieces
    ]
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
