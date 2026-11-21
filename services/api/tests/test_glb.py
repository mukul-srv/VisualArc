import io
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from api.cli import main
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import (
    Building,
    Floor,
    LineGeometry,
    Measured,
    Project,
    SourceRef,
    Wall,
)
from api.engine.exporters.glb import build_meta, build_scene
from api.engine.settings import DEFAULTS

FIXTURE_A = Path(__file__).resolve().parents[3] / "fixtures" / "input" / "fixture_a.dxf"


def _roundtrip(scene: trimesh.Scene) -> trimesh.Scene:
    return trimesh.load(io.BytesIO(scene.export(file_type="glb")), file_type="glb")


def _one_wall_project() -> Project:
    wall = Wall(
        id="w-1",
        centreline=LineGeometry(start=(0, 100), end=(4000, 100)),
        thickness=Measured(value=200, source="source_extracted"),
        height=Measured(value=3000, source="user_provided"),
        sources=[SourceRef(layer="A-WALL", entity_handle="1F")],
    )
    floor = Floor(
        id="f", name="L0", elevation=Measured(value=0, source="defaulted"), walls=[wall]
    )
    return Project(
        id="p", source_file="x.dxf", buildings=[Building(id="b", floors=[floor])]
    )


def test_axis_swap_and_metres():
    # plan x 0..4000, y 0..200, z_up 0..3000 mm -> glTF x 0..4, y 0..3, z -0.2..0 m
    loaded = _roundtrip(build_scene(_one_wall_project()))
    np.testing.assert_allclose(loaded.bounds, [[0, 0, -0.2], [4, 3, 0]], atol=1e-9)
    mesh = loaded.geometry["w-1"]
    assert mesh.is_watertight and mesh.volume > 0  # winding not flipped by swap
    assert mesh.volume == pytest.approx(4 * 0.2 * 3)


def test_fixture_a_metadata_roundtrip():
    project = read_dxf(FIXTURE_A, wall_height=3000, ceiling_height=3000)
    floor = project.buildings[0].floors[0]
    ids = {e.id for e in [*floor.walls, *floor.junctions, *floor.boundaries, *floor.ceilings]}
    loaded = _roundtrip(build_scene(project))

    assert set(loaded.graph.nodes_geometry) == ids
    np.testing.assert_allclose(loaded.extents, [8.2, 3.0, 5.2], atol=1e-9)
    assert loaded.metadata["schema_version"] == project.schema_version
    for w in floor.walls:
        extras = loaded.geometry[w.id].metadata
        assert extras["type"] == "wall"
        assert extras["thickness"] == {
            "value": w.thickness.value,
            "unit": "mm",
            "source": "source_extracted",
        }
        assert extras["height"]["source"] == "user_provided"
        assert {s["entity_handle"] for s in extras["sources"]} == {
            s.entity_handle for s in w.sources
        }
    for j in floor.junctions:
        assert loaded.geometry[j.id].metadata["source"] == "inferred"
    for b in floor.boundaries:  # floor faces point up (+Y) after the swap
        f = loaded.geometry[b.id]
        np.testing.assert_allclose(
            f.face_normals, [[0, 1, 0]] * len(f.faces), atol=1e-9
        )


def test_materials_per_kind_from_settings():
    project = read_dxf(FIXTURE_A, wall_height=3000, ceiling_height=3000)
    floor = project.buildings[0].floors[0]
    loaded = _roundtrip(build_scene(project))
    palette = dict(DEFAULTS.material_palette)

    def expect(el):
        if el.type == "wall":
            return f"wall_{el.role}" if el.role else "wall_neutral"
        return "wall_neutral" if el.type == "junction" else el.type

    seen = set()
    for el in [*floor.walls, *floor.junctions, *floor.boundaries, *floor.ceilings]:
        mat = loaded.geometry[el.id].visual.material
        hex_, rough = palette[expect(el)]
        assert list(mat.baseColorFactor[:3]) == [int(hex_[i : i + 2], 16) for i in (1, 3, 5)]
        assert mat.roughnessFactor == pytest.approx(rough)
        assert mat.metallicFactor == 0
        seen.add(expect(el))
    assert len(seen) > 1  # fixture exercises several kinds
    assert len({id(g.visual.material) for g in loaded.geometry.values()}) <= len(palette)


def test_meta_report_fixture_a():
    project = read_dxf(FIXTURE_A, wall_height=3000, ceiling_height=3000)
    scene = build_scene(project)
    meta = build_meta(project, scene)
    assert set(meta["elements"]) == set(scene.graph.nodes_geometry)
    np.testing.assert_allclose(
        meta["scene_bounds_m"], [[0, 0, -5.2], [8.2, 3, 0]], atol=1e-9
    )
    solids = [e for e in meta["elements"].values() if e["type"] not in ("floor_boundary", "ceiling")]
    assert all(e["watertight"] for e in solids)
    json.dumps(meta)  # must be serialisable as-is


def test_cli_build(tmp_path):
    main(["build", str(FIXTURE_A), "--wall-height", "3000", "--ceiling-height", "3000", "--out", str(tmp_path)])
    assert {p.name for p in tmp_path.iterdir()} == {
        "fixture_a.canonical.json",
        "fixture_a.glb",
        "fixture_a.meta.json",
        "fixture_a.report.md",
    }


def test_cli_build_blocked_without_height(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["build", str(FIXTURE_A), "--out", str(tmp_path)])
    assert exc.value.code == 1
    # evidence kept, no GLB produced from an incomplete model
    assert {p.name for p in tmp_path.iterdir()} == {
        "fixture_a.canonical.json",
        "fixture_a.report.md",
    }


def test_ceiling_mesh_faces_down_with_type_metadata():
    project = read_dxf(FIXTURE_A, wall_height=3000, ceiling_height=2600)
    floor = project.buildings[0].floors[0]
    loaded = _roundtrip(build_scene(project))
    assert floor.ceilings
    for c in floor.ceilings:
        m = loaded.geometry[c.id]
        assert m.metadata["type"] == "ceiling"
        assert m.metadata["elevation"]["source"] == "inferred"
        np.testing.assert_allclose(m.vertices[:, 1], 2.6, atol=1e-9)  # Y-up, metres
        np.testing.assert_allclose(m.face_normals, [[0, -1, 0]] * len(m.faces), atol=1e-9)
