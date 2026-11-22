"""Canonical project -> GLB scene + verification report.

The one place where ADR-001's conversion happens: mm -> m and
plan (x, y, z_up) -> glTF (x, z_up, -y). Each element is one node named by
its canonical id; its non-geometry fields (type, provenance, sources) ride
along as glTF mesh `extras` so the viewer can show them.
"""

import numpy as np
import trimesh

from api.engine.canonical.model import Project
from api.engine.geometry3d.extrude import (
    build_balcony_railings,
    build_meshes,
    build_opening_parts,
)
from api.engine.settings import DEFAULTS

# rotation part has det +1, so triangle winding (and normals) survive the swap
PLAN_MM_TO_GLTF_M = np.diag([0.001, 0.001, 0.001, 1.0]) @ np.array(
    [[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=float
)


def _elements(floor):
    return [*floor.walls, *floor.junctions, *floor.boundaries, *floor.slabs, *floor.columns, *floor.balconies, *floor.ceilings]


def material_key(el) -> str:
    if el.type == "wall":
        return f"wall_{el.role}" if el.role else "wall_neutral"
    return "wall_neutral" if el.type == "junction" else el.type


def build_scene(project: Project) -> trimesh.Scene:
    scene = trimesh.Scene()
    scene.metadata.update(
        schema_version=project.schema_version,
        project_id=project.id,
        source_file=project.source_file,
    )
    # one shared material per kind, not per mesh
    materials = {
        k: trimesh.visual.material.PBRMaterial(
            name=k,
            baseColorFactor=[*(int(h[i : i + 2], 16) for i in (1, 3, 5)), 110 if k == "opening_glass" else 255],
            roughnessFactor=r,
            metallicFactor=0.0,
            **({"alphaMode": "BLEND"} if k == "opening_glass" else {}),
        )
        for k, (h, r) in DEFAULTS.material_palette
    }
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
                if el.id not in meshes:  # a column without a height (reported): nothing to extrude
                    continue
                mesh = meshes[el.id]
                mesh.apply_transform(PLAN_MM_TO_GLTF_M)  # baked: viewer gets metres
                mesh.visual = trimesh.visual.TextureVisuals(
                    material=materials[material_key(el)]
                )
                mesh.metadata = {
                    "floor_id": floor.id,
                    **el.model_dump(mode="json", exclude={"centreline", "polygon"}),
                }
                if el.id in hosted:  # key absent otherwise: pre-T12 GLBs unchanged
                    mesh.metadata["openings"] = hosted[el.id]
                scene.add_geometry(mesh, node_name=el.id, geom_name=el.id)
            for pid, (bal, mesh) in build_balcony_railings(floor).items():
                mesh.apply_transform(PLAN_MM_TO_GLTF_M)
                mesh.visual = trimesh.visual.TextureVisuals(material=materials["balcony_railing"])
                mesh.metadata = {"floor_id": floor.id, "id": pid, "type": "balcony_railing",
                                 "balcony_id": bal.id, "height": bal.railing_height.model_dump(mode="json"),
                                 "thickness": bal.railing_thickness.model_dump(mode="json"),
                                 "sources": [s.model_dump(mode="json") for s in bal.sources]}
                scene.add_geometry(mesh, node_name=pid, geom_name=pid)
            for pid, (part, o, mesh) in build_opening_parts(floor).items():
                mesh.apply_transform(PLAN_MM_TO_GLTF_M)
                mesh.visual = trimesh.visual.TextureVisuals(material=materials[f"opening_{part}"])
                # `opening` (the whole record, swing and detail included) is what the inspector shows
                mesh.metadata = {"floor_id": floor.id, "id": pid, "type": "opening_part",
                                 "part": part, "opening": o.model_dump(mode="json")}
                scene.add_geometry(mesh, node_name=pid, geom_name=pid)
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
