"""Fixture C = Fixture A drawn with closed LWPOLYLINE walls and lower-case layers."""

from pathlib import Path

from api.engine.adapters.dxf.reader import read_dxf

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "input"


def _geometry(path: Path):
    p = read_dxf(path, wall_height=3000, ceiling_height=3000)
    f = p.buildings[0].floors[0]
    walls = sorted(
        (
            w.centreline.start,
            w.centreline.end,
            w.thickness.value,
            w.thickness.source,
            w.height.value,
            w.height.source,
        )
        for w in f.walls
    )
    junctions = sorted((tuple(j.polygon), j.source) for j in f.junctions)
    boundaries = sorted(tuple(b.polygon) for b in f.boundaries)
    issues = [(i.code, i.severity) for i in p.issues]
    return walls, junctions, boundaries, issues, f.elevation


def test_fixture_c_matches_fixture_a_geometry():
    a = _geometry(FIXTURES / "fixture_a.dxf")
    c = _geometry(FIXTURES / "fixture_c.dxf")
    assert len(a[0]) == 7  # guards against both sides being empty
    assert c == a


def test_fixture_c_source_refs_use_actual_layer_and_polyline_handles():
    f = read_dxf(FIXTURES / "fixture_c.dxf", 3000, ceiling_height=3000).buildings[0].floors[0]
    refs = {(s.layer, s.entity_handle) for w in f.walls for s in w.sources}
    assert {layer for layer, _ in refs} == {"a-wall"}
    assert len({h for _, h in refs}) == 3  # three polylines, not 12 lines
