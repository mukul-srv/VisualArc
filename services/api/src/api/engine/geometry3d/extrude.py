"""Canonical floor -> triangle meshes, one per element.

Output stays in plan space: millimetres, X/Y = plan, Z up, Z=0 at datum.
The swap to glTF Y-up (ADR-001) belongs to the exporter, not here.
"""

import numpy as np
import trimesh
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from api.engine.canonical.model import Floor, Opening, Wall


def _height(w: Wall) -> float:
    if w.height is None:  # reader already raised a blocking issue for this
        raise ValueError(f"{w.id} has no height; cannot extrude")
    return w.height.value


def _prism(footprint: Polygon, z0: float, height: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.extrude_polygon(footprint, height)
    mesh.apply_translation((0, 0, z0))
    return mesh


def _flat(polygon: Polygon, z: float, up: bool = True) -> trimesh.Trimesh:
    # no slab thickness in the canonical model -> zero-thickness surface
    v2, faces = trimesh.creation.triangulate_polygon(orient(polygon, 1.0))
    v3 = np.column_stack([v2, np.full(len(v2), z)])
    return trimesh.Trimesh(v3, faces if up else faces[:, ::-1], process=True)


def _wall_with_openings(
    w: Wall, openings: list[Opening], z0: float, height: float
) -> trimesh.Trimesh:
    """Elevation profile (u along centreline, v up) minus apertures, extruded
    through the full thickness, then placed on the centreline: one closed mesh."""
    start, end = np.array(w.centreline.start), np.array(w.centreline.end)
    length = float(np.linalg.norm(end - start))
    d = (end - start) / length
    holes = []
    for o in openings:  # u from the span itself, so exact even if start > end
        us = sorted(
            float(np.dot(np.array(p) - start, d)) for p in (o.span.start, o.span.end)
        )
        top = o.sill_height.value + o.height.value
        holes.append(box(us[0], o.sill_height.value, us[1], top))
    profile = box(0, 0, length, height).difference(unary_union(holes))
    # a full-height aperture splits the wall into separate closed pieces
    parts = getattr(profile, "geoms", [profile])
    t = w.thickness.value
    mesh = trimesh.util.concatenate(
        [trimesh.creation.extrude_polygon(p, t) for p in parts]
    )
    # local (u, v, w) -> plan; n = (dy, -dx) makes det = +1, so winding survives
    nx, ny = d[1], -d[0]
    sx, sy = start - np.array([nx, ny]) * t / 2
    mesh.apply_transform(
        [[d[0], 0, nx, sx], [d[1], 0, ny, sy], [0, 1, 0, z0], [0, 0, 0, 1]]
    )
    return mesh


def build_meshes(floor: Floor) -> dict[str, trimesh.Trimesh]:
    """Element id -> mesh for every wall, junction and floor boundary."""
    z0 = floor.elevation.value
    heights = {w.id: _height(w) for w in floor.walls}
    hosted: dict[str, list[Opening]] = {}
    for o in floor.openings:
        hosted.setdefault(o.wall_id, []).append(o)
    meshes = {}
    for w in floor.walls:
        if w.id in hosted:
            meshes[w.id] = _wall_with_openings(w, hosted[w.id], z0, heights[w.id])
            continue
        # unchanged path: walls without openings stay byte-identical to pre-T12
        line = LineString([w.centreline.start, w.centreline.end])
        rect = line.buffer(w.thickness.value / 2, cap_style="flat")
        meshes[w.id] = _prism(rect, z0, heights[w.id])
    for j in floor.junctions:
        # corner fill must reach the tallest wall it joins, else a notch shows
        meshes[j.id] = _prism(
            Polygon(j.polygon), z0, max(heights[i] for i in j.wall_ids)
        )
    for b in floor.boundaries:
        meshes[b.id] = _flat(Polygon(b.polygon), z0)
    for c in floor.ceilings:  # underside faces down so it shows from inside
        meshes[c.id] = _flat(Polygon(c.polygon), c.elevation.value, up=False)
    return meshes
