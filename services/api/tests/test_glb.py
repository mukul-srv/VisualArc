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
    project = read_dxf(FIXTURE_A, wall_height=3000)
    floor = project.buildings[0].floors[0]
    ids = {e.id for e in [*floor.walls, *floor.junctions, *floor.boundaries]}
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


def test_meta_report_fixture_a():
    project = read_dxf(FIXTURE_A, wall_height=3000)
    scene = build_scene(project)
    meta = build_meta(project, scene)
    assert set(meta["elements"]) == set(scene.graph.nodes_geometry)
    np.testing.assert_allclose(
        meta["scene_bounds_m"], [[0, 0, -5.2], [8.2, 3, 0]], atol=1e-9
    )
    solids = [e for e in meta["elements"].values() if e["type"] != "floor_boundary"]
    assert all(e["watertight"] for e in solids)
    json.dumps(meta)  # must be serialisable as-is


def test_cli_build(tmp_path):
    main(["build", str(FIXTURE_A), "--wall-height", "3000", "--out", str(tmp_path)])
    assert {p.name for p in tmp_path.iterdir()} == {
        "fixture_a.canonical.json",
        "fixture_a.glb",
        "fixture_a.meta.json",
    }


def test_cli_build_blocked_without_height(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["build", str(FIXTURE_A), "--out", str(tmp_path)])
    assert exc.value.code == 1
    # evidence kept, no GLB produced from an incomplete model
    assert {p.name for p in tmp_path.iterdir()} == {"fixture_a.canonical.json"}
