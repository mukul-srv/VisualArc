import pytest

from api.engine.geometry2d.walls import Segment, find_junctions, pair_walls


def segs(*lines):
    return [Segment(f"H{i}", "A-WALL", a, b) for i, (a, b) in enumerate(lines)]


def run(lines):
    s = segs(*lines)
    walls, issues = pair_walls(s)
    junctions, j_issues = find_junctions(s, walls)
    return walls, junctions, issues + j_issues


def codes(issues):
    return sorted(i.code for i in issues)


def test_single_wall_partial_overlap():
    walls, junctions, issues = run([((0, 0), (1000, 0)), ((800, 200), (200, 200))])
    assert len(walls) == 1 and not issues and not junctions
    w = walls[0]
    assert w.start == (200, 100) and w.end == (800, 100)
    assert w.thickness == pytest.approx(200, abs=1e-6)
    assert [s.handle for s in w.sources] == ["H0", "H1"]


def test_l_corner_gets_one_junction():
    walls, junctions, issues = run(
        [
            ((0, 0), (1000, 0)),
            ((200, 200), (1000, 200)),  # horizontal wall faces
            ((0, 0), (0, 1000)),
            ((200, 200), (200, 1000)),  # vertical wall faces
            ((1000, 0), (1000, 200)),
            ((0, 1000), (200, 1000)),  # end caps
        ]
    )
    assert len(walls) == 2
    assert [j.polygon for j in junctions] == [[(0, 0), (200, 0), (200, 200), (0, 200)]]
    assert sorted(junctions[0].wall_ids) == sorted(w.id for w in walls)
    # shortcut-documenting: end caps have no partner, reported not hidden
    assert codes(issues) == ["unpaired_segment"] * 2


def test_t_junction_fills_gap_under_stem():
    walls, junctions, issues = run(
        [
            ((0, 0), (2000, 0)),
            ((0, 200), (900, 200)),
            ((1100, 200), (2000, 200)),
            ((900, 200), (900, 1200)),
            ((1100, 200), (1100, 1200)),
            ((0, 0), (0, 200)),
            ((2000, 0), (2000, 200)),
            ((900, 1200), (1100, 1200)),
        ]
    )
    assert sorted((w.start, w.end, w.thickness) for w in walls) == [
        ((0, 100), (900, 100), 200),
        ((1000, 200), (1000, 1200), 200),
        ((1100, 100), (2000, 100), 200),
    ]
    assert [j.polygon for j in junctions] == [
        [(900, 0), (1100, 0), (1100, 200), (900, 200)]
    ]
    assert len(junctions[0].wall_ids) == 3
    assert codes(issues) == ["unpaired_segment"] * 3


def test_closed_room_four_walls_four_corners_area_conserved():
    outer = [(0, 0), (1400, 0), (1400, 1200), (0, 1200)]
    inner = [(200, 200), (1200, 200), (1200, 1000), (200, 1000)]
    ring = lambda p: list(zip(p, p[1:] + p[:1]))
    walls, junctions, issues = run(ring(outer) + ring(inner))
    assert not issues and len(walls) == 4 and len(junctions) == 4
    area = sum(w.rect().area for w in walls) + 4 * 200 * 200
    assert area == pytest.approx(1400 * 1200 - 1000 * 800, abs=1e-6)
    assert {w.thickness for w in walls} == {200}


def test_unpaired_line_warns_with_handle():
    walls, _, issues = run(
        [((0, 0), (1000, 0)), ((0, 200), (1000, 200)), ((5000, 5000), (6000, 5000))]
    )
    assert len(walls) == 1
    assert [(i.code, i.severity, i.sources[0].entity_handle) for i in issues] == [
        ("unpaired_segment", "warning", "H2")
    ]


def test_ambiguous_triple_line_is_blocking_not_guessed():
    walls, _, issues = run(
        [((0, 0), (1000, 0)), ((0, 200), (1000, 200)), ((0, 400), (1000, 400))]
    )
    assert walls == []
    assert issues and all(i.severity == "blocking" for i in issues)
    assert "H1" in {s.entity_handle for i in issues for s in i.sources}


def test_non_orthogonal_and_degenerate_segments_warn():
    _, _, issues = run([((0, 0), (1000, 500)), ((5, 5), (5, 5))])
    assert codes(issues) == ["degenerate_segment", "non_orthogonal_segment"]
