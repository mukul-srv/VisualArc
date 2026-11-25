"""Canonical floors -> one OBJ, reusing the GLB scene builder (same metres, same Y-up axes as the GLB)."""

import numpy as np
import trimesh

from api.engine.canonical.model import Project
from api.engine.exporters.glb import build_scene


def build_obj(floors: list[tuple[Project, tuple[float, float]]]) -> tuple[str, trimesh.Scene]:
    """`floors`: (single-floor project, plan offset in mm) per floor. Returns (OBJ text, merged scene).
    Names are prefixed with the floor id since element ids repeat across floors."""
    merged = trimesh.Scene()
    for project, (dx, dy) in floors:
        prefix = project.buildings[0].floors[0].id
        shift = np.eye(4)
        shift[:3, 3] = (dx / 1000, 0, -dy / 1000)  # plan (x, y) -> glTF (x, -y), as PLAN_MM_TO_GLTF_M
        scene = build_scene(project)
        for node in scene.graph.nodes_geometry:
            mesh = scene.geometry[scene.graph[node][1]].copy()
            mesh.apply_transform(shift)
            merged.add_geometry(mesh, node_name=f"{prefix}_{node}", geom_name=f"{prefix}_{node}")
    return merged.export(file_type="obj", include_normals=False), merged
