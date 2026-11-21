"""Canonical project -> GLB scene + verification report.

The one place where ADR-001's conversion happens: mm -> m and
plan (x, y, z_up) -> glTF (x, z_up, -y). Each element is one node named by
its canonical id; its non-geometry fields (type, provenance, sources) ride
along as glTF mesh `extras` so the viewer can show them.
"""

import numpy as np
import trimesh

from api.engine.canonical.model import Project
from api.engine.geometry3d.extrude import build_meshes

# rotation part has det +1, so triangle winding (and normals) survive the swap
PLAN_MM_TO_GLTF_M = np.diag([0.001, 0.001, 0.001, 1.0]) @ np.array(
    [[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=float
)


def _elements(floor):
    return [*floor.walls, *floor.junctions, *floor.boundaries, *floor.ceilings]


def build_scene(project: Project) -> trimesh.Scene:
    scene = trimesh.Scene()
    scene.metadata.update(
        schema_version=project.schema_version,
        project_id=project.id,
        source_file=project.source_file,
    )
    for building in project.buildings:
        for floor in building.floors:
            meshes = build_meshes(floor)
            hosted: dict[str, list[dict]] = {}
            for o in floor.openings:  # openings have no node; they ride on the host
                hosted.setdefault(o.wall_id, []).append(
                    o.model_dump(
                        mode="json"
                    )  # span (plan mm) lets the viewer map a click to it
                )
            for el in _elements(floor):
                mesh = meshes[el.id]
                mesh.apply_transform(PLAN_MM_TO_GLTF_M)  # baked: viewer gets metres
                mesh.metadata = {
                    "floor_id": floor.id,
                    **el.model_dump(mode="json", exclude={"centreline", "polygon"}),
                }
                if el.id in hosted:  # key absent otherwise: pre-T12 GLBs unchanged
                    mesh.metadata["openings"] = hosted[el.id]
                scene.add_geometry(mesh, node_name=el.id, geom_name=el.id)
    return scene


def build_meta(project: Project, scene: trimesh.Scene) -> dict:
    """Sidecar report keyed by node name; independent of GLB extras surviving."""
    elements = {}
    for name in scene.graph.nodes_geometry:
        mesh = scene.geometry[scene.graph[name][1]]
        elements[name] = {
            **mesh.metadata,
            "bounds_m": mesh.bounds.round(9).tolist(),
            "watertight": bool(mesh.is_watertight),
            "triangles": len(mesh.faces),
        }
    return {
        "schema_version": project.schema_version,
        "project_id": project.id,
        "source_file": project.source_file,
        "units": {"canonical": "mm", "glb": "m"},
        "axes": "plan (x, y, z_up) -> glTF (x, z_up, -y)",
        "scene_bounds_m": scene.bounds.round(9).tolist() if elements else None,
        "issues": [i.model_dump(mode="json") for i in project.issues],
        "elements": elements,
    }
