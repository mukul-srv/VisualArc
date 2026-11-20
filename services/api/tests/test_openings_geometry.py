"""T12: wall solids with apertures. Expectations come from ADR-002 (worked example,
section 5/8) and the table in scripts/make_fixture_openings.py, never from output."""

import io
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh
from shapely.geometry import LineString

from api.cli import main
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import (
    Floor,
    LineGeometry,
    Measured,
    Opening,
    SourceRef,
    Wall,
)
from api.engine.exporters.glb import build_scene
from api.engine.geometry3d.extrude import _prism, build_meshes

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "input"
REF = [SourceRef(layer="A-WALL", entity_handle="1")]
# Relative volume tolerance: apertures are exact boxes, so only float noise from the
# placement transform (~1e-16) can appear; 1e-6 leaves ample margin yet catches any
# real error (smallest feature, a 1 mm slip on a 5000 mm wall, is 2e-4).
VOL_TOL = 1e-6


def M(v, s="source_extracted"):
    return Measured(value=v, source=s)


def _wall(start, end, thk=200.0, h=2700.0) -> Wall:
    return Wall(
        id="w",
        centreline=LineGeometry(start=start, end=end),
        thickness=M(thk),
        height=M(h, "user_provided"),
        sources=REF,
    )


def _op(i, wall, a, b, sill, h, kind="door") -> Opening:
    """Opening on an axis-aligned wall; a < b are coordinates along the wall axis."""
    (x0, y0), (_, y1) = wall.centreline.start, wall.centreline.end
    horiz = y0 == y1
    s, e = ((a, y0), (b, y0)) if horiz else ((x0, a), (x0, b))
    off = abs(s[0] - x0) + abs(s[1] - y0)  # distance from centreline.start
    return Opening(
        id=f"opening-{i:03d}",
        kind=kind,
        wall_id=wall.id,
        span=LineGeometry(start=s, end=e),
        offset=M(off),
        width=M(b - a),
        height=M(h),
        sill_height=M(sill),
        sources=REF,
    )


def _mesh(wall, ops, z=0.0):
    floor = Floor(
        id="f", name="L0", elevation=M(z, "defaulted"), walls=[wall], openings=ops
    )
    return build_meshes(floor)["w"]


def _hit(mesh, origin, direction=(0, 1, 0)):
    """Any triangle crossed by the ray (Moller-Trumbore; trimesh's ray needs rtree)."""
    o, d = np.array(origin, float), np.array(direction, float)
    tri = mesh.triangles
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
    s = o - tri[:, 0]
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    v = (q @ d) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    return bool(np.any(ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)))


def _solid(m):
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0


# ADR-002 worked example: wall 5000 x 200 x 2700, door 1000..1900, window 3000..3600
def _example():
    w = _wall((0, 100), (5000, 100))
    return w, [
        _op(1, w, 1000, 1900, 0, 2100),
        _op(2, w, 3000, 3600, 900, 1200, "window"),
    ]


def test_worked_example_volume_and_closure():
    m = _mesh(*_example())
    _solid(m)
    assert m.volume == pytest.approx(2.178e9, rel=VOL_TOL)
    np.testing.assert_allclose(m.bounds, [[0, 0, 0], [5000, 200, 2700]], atol=1e-6)


def test_aperture_bounds_exact():
    m = _mesh(*_example())
    e = 1.0  # probe 1 mm inside/outside each edge; rays cross the full thickness

    def clear(u, z):
        return not _hit(m, (u, -50, z))

    # door 1000..1900, z 0..2100
    assert clear(1450, 1000)
    assert clear(1000 + e, 1000) and clear(1900 - e, 1000)
    assert not clear(1000 - e, 1000) and not clear(1900 + e, 1000)
    assert clear(1450, 2100 - e) and not clear(1450, 2100 + e)  # lintel soffit
    # window 3000..3600, z 900..2100
    assert clear(3300, 1500)
    assert clear(3000 + e, 1500) and clear(3600 - e, 1500)
    assert not clear(3000 - e, 1500) and not clear(3600 + e, 1500)
    assert clear(3300, 900 + e) and not clear(3300, 900 - e)  # sill top
    assert clear(3300, 2100 - e) and not clear(3300, 2100 + e)  # window lintel
    # solid wall elsewhere, including the 1 mm-from-top strip above the door
    assert not clear(2500, 1000) and not clear(1450, 2699)


def test_open_top_notch_full_height_split_adjacent():
    w = _wall((0, 100), (4000, 100))
    # sill + height == wall height: open-top notch, still closed solid
    m = _mesh(w, [_op(1, w, 1000, 1500, 900, 1800, "window")])
    _solid(m)
    assert m.volume == pytest.approx(4000 * 200 * 2700 - 500 * 200 * 1800, rel=VOL_TOL)
    assert not _hit(m, (1250, -50, 2699)) and _hit(m, (1250, -50, 800))
    # sill 0 and height == wall height splits the wall into two closed pieces
    m = _mesh(w, [_op(1, w, 1000, 1900, 0, 2700)])
    _solid(m)
    assert not _hit(m, (1450, -50, 1350)) and not _hit(m, (1450, -50, 2699))
    assert _hit(m, (999, -50, 2699)) and _hit(m, (1901, -50, 2699))
    assert m.volume == pytest.approx((4000 - 900) * 200 * 2700, rel=VOL_TOL)
    # sill 0 door (notch in the bottom), two adjacent openings, 100 mm mullion
    ops = [_op(1, w, 500, 1000, 0, 2100), _op(2, w, 1100, 1700, 900, 1200, "window")]
    m = _mesh(w, ops)
    _solid(m)
    assert m.volume == pytest.approx(
        4000 * 200 * 2700 - 500 * 200 * 2100 - 600 * 200 * 1200, rel=VOL_TOL
    )
    assert _hit(m, (1050, -50, 1000)) and not _hit(m, (750, -50, 1000))
    assert not _hit(m, (750, -50, 5))  # door really reaches the floor


@pytest.mark.parametrize(
    "start,end",
    [
        ((0, 100), (4000, 100)),  # horizontal, low -> high
        ((4000, 100), (0, 100)),  # horizontal, high -> low
        ((100, 0), (100, 4000)),  # vertical, low -> high
        ((100, 4000), (100, 0)),  # vertical, high -> low
    ],
)
def test_orientations_and_floor_offset(start, end):
    w = _wall(start, end)
    horiz = start[1] == end[1]
    # axis coordinates are absolute plan coordinates, independent of direction
    ops = [_op(1, w, 1000, 1900, 0, 2100), _op(2, w, 3000, 3600, 900, 1200, "window")]
    z = 500.0
    m = _mesh(w, ops, z)
    _solid(m)
    expect = 4000 * 200 * 2700 - 900 * 200 * 2100 - 600 * 200 * 1200
    assert m.volume == pytest.approx(expect, rel=VOL_TOL)
    top = [4000, 200] if horiz else [200, 4000]
    np.testing.assert_allclose(m.bounds, [[0, 0, z], [*top, z + 2700]], atol=1e-6)

    def clear(a, zz):  # ray across the thickness at axis coordinate a, height zz
        o, d = [0.0] * 3, [0.0] * 3
        o[0 if horiz else 1], o[1 if horiz else 0], o[2] = a, -50, zz
        d[1 if horiz else 0] = 1
        return not _hit(m, o, d)

    assert clear(1450, z + 1000) and not clear(1450, z + 2400)
    assert clear(3300, z + 1500) and not clear(3300, z + 500)
    assert not clear(999, z + 1000) and not clear(1901, z + 1000)


# fixture_openings: ADR/generator table. Key = merged wall centreline start;
# value = (length, thickness, [(aperture width, aperture height)]); door h 2100, window h 1200.
H = 3000
WALLS = {
    (200, 100): (3000, 200, [(500, 1200)]),  # B1: opening-001 window
    (3300, 100): (3000, 200, [(1200, 1200)]),  # B2: 002 window
    (6400, 100): (3000, 200, [(900, 2100)]),  # B3: 003 door
    (100, 200): (3600, 200, [(900, 1200)]),  # L: 005 window
    (3250, 200): (3600, 100, [(900, 2100)]),  # I1: 004 door
    (6350, 200): (3600, 100, [(800, 2100)]),  # I2: 007 door
    (9500, 200): (3600, 200, [(1200, 1200)]),  # R: 006 window
    (200, 3900): (3000, 200, []),
    (3300, 3900): (3000, 200, []),
    (6400, 3900): (3000, 200, []),
}


@pytest.fixture(scope="module")
def fo_project():
    return read_dxf(FIX / "fixture_openings.dxf", wall_height=H)


def test_fixture_openings_wall_volumes(fo_project):
    floor = fo_project.buildings[0].floors[0]
    meshes = build_meshes(floor)
    assert len(floor.walls) == len(WALLS)
    for w in floor.walls:
        length, t, aps = WALLS[tuple(w.centreline.start)]
        exp = length * t * H - sum(a * t * h for a, h in aps)
        m = meshes[w.id]
        assert m.is_watertight and m.is_winding_consistent, w.id
        assert m.volume == pytest.approx(exp, rel=VOL_TOL), w.id
    for el in floor.junctions:
        assert meshes[el.id].is_watertight


def test_fixture_openings_glb_roundtrip_and_meta(fo_project, tmp_path):
    floor = fo_project.buildings[0].floors[0]
    ids = {e.id for e in [*floor.walls, *floor.junctions, *floor.boundaries]}
    loaded = trimesh.load(
        io.BytesIO(build_scene(fo_project).export(file_type="glb")), file_type="glb"
    )
    assert set(loaded.graph.nodes_geometry) == ids
    n = 0
    for w in floor.walls:
        meta = loaded.geometry[w.id].metadata
        ex = meta.get("extras", meta)
        mine = [o for o in floor.openings if o.wall_id == w.id]
        if not mine:
            assert "openings" not in ex
            continue
        assert [o["id"] for o in ex["openings"]] == [o.id for o in mine]
        for got, o in zip(ex["openings"], mine, strict=True):
            n += 1
            assert got["kind"] == o.kind and got["width"]["value"] == o.width.value
            assert got["sill_height"]["source"] == "defaulted"  # provenance kept
            assert got["offset"]["source"] == "source_extracted"
            assert got["span"]["start"] == list(o.span.start)  # viewer picking needs it
            assert got["span"]["end"] == list(o.span.end)
    assert n == 7
    out = tmp_path / "o"
    dxf = str(FIX / "fixture_openings.dxf")
    main(["build", dxf, "--wall-height", "3000", "--out", str(out)])
    meta = json.loads((out / "fixture_openings.meta.json").read_text())
    hosted = [v["openings"] for v in meta["elements"].values() if "openings" in v]
    assert sum(len(h) for h in hosted) == 7
    solids = [v for v in meta["elements"].values() if v["type"] != "floor_boundary"]
    assert all(v["watertight"] for v in solids)  # boundaries are flat polygons
    # 9.6 x 3.0 x 4.0 m, glTF Y-up: plan y 0..4 m -> z -4..0
    np.testing.assert_allclose(
        meta["scene_bounds_m"], [[0, 0, -4], [9.6, 3, 0]], atol=1e-9
    )


@pytest.mark.parametrize("name", ["fixture_a", "fixture_b"])
def test_no_openings_means_plain_prism(name):
    """Fixtures A/B: no openings key; meshes equal the pre-T12 prism construction."""
    proj = read_dxf(FIX / f"{name}.dxf", wall_height=3000)
    floor = proj.buildings[0].floors[0]
    assert not floor.openings
    meshes = build_meshes(floor)
    for w in floor.walls:
        rect = LineString([w.centreline.start, w.centreline.end]).buffer(
            w.thickness.value / 2, cap_style="flat"
        )
        ref = _prism(rect, floor.elevation.value, 3000.0)
        assert np.array_equal(meshes[w.id].vertices, ref.vertices)
        assert np.array_equal(meshes[w.id].faces, ref.faces)
    for mesh in build_scene(proj).geometry.values():
        assert "openings" not in mesh.metadata
