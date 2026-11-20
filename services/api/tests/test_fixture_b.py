import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from api.cli import main
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.geometry3d.extrude import build_meshes

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
FIXTURE_B = FIXTURES / "input" / "fixture_b.dxf"


def test_fixture_b_l_shaped_room():
    p = read_dxf(FIXTURE_B, wall_height=3000)
    assert p.issues == []
    f = p.buildings[0].floors[0]
    assert len(f.walls) == 6 and len(f.junctions) == 6  # 5 convex + 1 reflex corner
    assert {w.thickness.value for w in f.walls} == {200}
    assert [b.polygon for b in f.boundaries] == [
        [(200, 200), (5800, 200), (5800, 2800), (2800, 2800), (2800, 4800), (200, 4800)]
    ]

    meshes = build_meshes(f)
    solids = [meshes[e.id] for e in [*f.walls, *f.junctions]]
    assert all(m.is_watertight for m in solids)
    np.testing.assert_allclose(
        trimesh.util.concatenate(solids).bounds,
        [[0, 0, 0], [6000, 5000, 3000]],
        atol=1e-6,
    )
    outer, room = 6000 * 3000 + 3000 * 2000, 5600 * 2600 + 2600 * 2000
    assert sum(m.volume for m in solids) == pytest.approx((outer - room) * 3000)
    assert meshes[f.boundaries[0].id].area == pytest.approx(room)


def test_fixture_b_snapshot(tmp_path: Path):
    out = tmp_path / "b.json"
    main(["interpret", str(FIXTURE_B), "--wall-height", "3000", "--out", str(out)])
    expected = json.loads(
        (FIXTURES / "expected" / "fixture_b.canonical.json").read_text()
    )
    assert json.loads(out.read_text()) == expected
