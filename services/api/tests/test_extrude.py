from pathlib import Path

import numpy as np
import pytest
import trimesh

from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import Floor, LineGeometry, Measured, SourceRef, Wall
from api.engine.geometry3d.extrude import build_meshes

FIXTURE_A = Path(__file__).resolve().parents[3] / "fixtures" / "input" / "fixture_a.dxf"
REF = [SourceRef(layer="A-WALL", entity_handle="1")]


def _wall(start, end, thk=200.0, height=3000.0) -> Wall:
    return Wall(
        id="w",
        centreline=LineGeometry(start=start, end=end),
        thickness=Measured(value=thk, source="source_extracted"),
        height=None
        if height is None
        else Measured(value=height, source="user_provided"),
        sources=REF,
    )


def _floor(walls, z=0.0) -> Floor:
    return Floor(
        id="f", name="L0", elevation=Measured(value=z, source="defaulted"), walls=walls
    )


@pytest.mark.parametrize(
    "start,end,bounds",
    [
        ((0, 100), (4000, 100), [[0, 0, 500], [4000, 200, 3500]]),  # horizontal
        ((100, 0), (100, 4000), [[0, 0, 500], [200, 4000, 3500]]),  # vertical
    ],
)
def test_wall_prism_dimensions(start, end, bounds):
    m = build_meshes(_floor([_wall(start, end)], z=500))["w"]
    assert m.is_watertight
    np.testing.assert_allclose(m.bounds, bounds, atol=1e-6)
    assert m.volume == pytest.approx(4000 * 200 * 3000)


def test_missing_height_refuses():
    with pytest.raises(ValueError, match="no height"):
        build_meshes(_floor([_wall((0, 0), (1000, 0), height=None)]))


def test_fixture_a_meshes():
    floor = read_dxf(FIXTURE_A, wall_height=3000, ceiling_height=3000).buildings[0].floors[0]
    meshes = build_meshes(floor)
    solids = [meshes[e.id] for e in [*floor.walls, *floor.junctions]]
    assert all(m.is_watertight for m in solids)
    # walls + junctions tile the outer footprint exactly: 8200 x 5200 x 3000
    np.testing.assert_allclose(
        trimesh.util.concatenate(solids).bounds,
        [[0, 0, 0], [8200, 5200, 3000]],
        atol=1e-6,
    )
    # wall material = footprint minus the two room interiors
    rooms = 4000 * 4800 + 3700 * 4800
    assert sum(m.volume for m in solids) == pytest.approx((8200 * 5200 - rooms) * 3000)
    for b in floor.boundaries:
        f = meshes[b.id]
        assert f.area == pytest.approx(4000 * 4800 if b.id == "fb-001" else 3700 * 4800)
        np.testing.assert_allclose(
            f.face_normals, [[0, 0, 1]] * len(f.faces), atol=1e-9
        )
        assert np.all(f.vertices[:, 2] == 0)
