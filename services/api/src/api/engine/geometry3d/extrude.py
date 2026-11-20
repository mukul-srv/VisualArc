"""Canonical floor -> triangle meshes, one per element.

Output stays in plan space: millimetres, X/Y = plan, Z up, Z=0 at datum.
The swap to glTF Y-up (ADR-001) belongs to the exporter, not here.
"""

import numpy as np
import trimesh
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from api.engine.canonical.model import Floor, Wall


def _height(w: Wall) -> float:
    if w.height is None:  # reader already raised a blocking issue for this
        raise ValueError(f"{w.id} has no height; cannot extrude")
    return w.height.value


def _prism(footprint: Polygon, z0: float, height: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.extrude_polygon(footprint, height)
    mesh.apply_translation((0, 0, z0))
    return mesh


def _flat(polygon: Polygon, z: float) -> trimesh.Trimesh:
    # no slab thickness in the canonical model -> zero-thickness surface, facing up
    v2, faces = trimesh.creation.triangulate_polygon(orient(polygon, 1.0))
    v3 = np.column_stack([v2, np.full(len(v2), z)])
    return trimesh.Trimesh(v3, faces, process=True)


def build_meshes(floor: Floor) -> dict[str, trimesh.Trimesh]:
    """Element id -> mesh for every wall, junction and floor boundary."""
    z0 = floor.elevation.value
    heights = {w.id: _height(w) for w in floor.walls}
    meshes = {}
    for w in floor.walls:
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
    return meshes
