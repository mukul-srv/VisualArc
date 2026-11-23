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
    # end caps have no partner: since the cap rule they are consumed as the walls' ends, in one report
    assert codes(issues) == ["wall_end_caps_consumed"]
    assert len([i for i in issues if i.code == "wall_end_caps_consumed"][0].sources) == 2


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
    assert codes(issues) == ["wall_end_caps_consumed"]  # the three end caps, one report


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


def _overlaps(issues):
    return [
        (i.severity, sorted(s.entity_handle for s in i.sources))
        for i in issues
        if i.code == "overlapping_wall_lines"
    ]


@pytest.mark.parametrize(
    "dup",
    [
        ((0, 0), (1000, 0)),  # exact duplicate
        ((1000, 0), (0, 0)),  # duplicate drawn reversed
        ((500, 0), (1500, 0)),  # partial overlap
        ((200, 0), (700, 0)),  # contained
    ],
)
def test_overlapping_collinear_lines_are_merged_and_reported(dup):
    # the same line drawn twice: merged (same points, nothing measured changes), warning not blocking
    walls, _, issues = run([((0, 0), (1000, 0)), ((0, 200), (1000, 200)), dup])
    assert _overlaps(issues) == [("warning", ["H0", "H2"])]
    assert [(w.thickness, w.start, w.end) for w in walls] == [(200, (0, 100), (1000, 100))]
    assert not [i for i in issues if i.severity == "blocking"]


def test_wall_changing_thickness_is_not_ambiguous():
    # one long face, partners at different offsets along different stretches: each pairs its own stretch
    walls, _, issues = run([((0, 0), (2000, 0)), ((0, 100), (1000, 100)), ((1000, 550), (2000, 550))])
    assert sorted((w.thickness, w.start[0], w.end[0]) for w in walls) == [(100, 0, 1000), (550, 1000, 2000)]
    assert not [i for i in issues if i.severity == "blocking"]


def test_end_to_end_collinear_lines_not_overlap():
    walls, _, issues = run(
        [((0, 0), (1000, 0)), ((1000, 0), (2000, 0)), ((0, 200), (2000, 200))]
    )
    assert _overlaps(issues) == [] and len(walls) == 2  # split face, one long face


def test_unexplained_region_carries_touching_wall_sources():
    _, junctions, issues = run(
        [
            ((0, 0), (1000, 0)),
            ((0, 200), (1000, 200)),  # the only wall
            ((1000, 0), (2000, 0)),
            ((2000, 0), (2000, 900)),
            ((2000, 900), (1000, 900)),
            ((1000, 900), (1000, 200)),
            ((0, 0), (0, 200)),  # region 1000x900 hangs off the wall: too big
        ]
    )
    (region,) = [i for i in issues if i.code == "unexplained_region"]
    assert junctions == []
    assert sorted(s.entity_handle for s in region.sources) == ["H0", "H1"]


def test_non_orthogonal_and_degenerate_segments_warn():
    _, _, issues = run([((0, 0), (1000, 500)), ((5, 5), (5, 5))])
    assert codes(issues) == ["degenerate_segment", "non_orthogonal_segment"]


def test_overlapping_lines_on_different_layers_are_not_merged():
    # the layer carries the wall role: the same line on an exterior and an interior layer is a conflict
    segs = [
        Segment("H0", "A-WALL-EXTR", (0, 0), (1000, 0)),
        Segment("H1", "A-WALL-EXTR", (0, 200), (1000, 200)),
        Segment("H2", "A-WALL-INTR", (0, 0), (1000, 0)),
    ]
    _, issues = pair_walls(segs)
    assert [(i.code, i.severity) for i in issues if i.code == "overlapping_wall_lines"] == [
        ("overlapping_wall_lines", "blocking")
    ]


def test_dominant_partner_resolves_ambiguity_and_lists_the_rejected():
    # a 2000 mm face with its wall partner 100 mm away, and a 50 mm stub of another line 550 mm away
    walls, _, issues = run([((0, 0), (2000, 0)), ((0, 100), (2000, 100)), ((1950, 550), (2000, 550))])
    assert [(w.thickness, w.start, w.end) for w in walls] == [(100, (0, 50), (2000, 50))]
    found = [i for i in issues if i.code == "ambiguous_pairing_resolved"]  # one per face that had both
    assert found and all(i.severity == "warning" and "rejected H2" in i.message for i in found)
    assert all({s.entity_handle for s in i.sources} >= {"H2"} for i in found)
    assert not [i for i in issues if i.severity == "blocking"]


def test_stray_line_beside_an_existing_wall_is_left_unpaired_not_blocking():
    # a 50 mm stub 450 and 550 mm from the two faces of a long wall: neither partner dominates, but the faces
    # already pair with each other over a far longer stretch
    walls, _, issues = run([((0, -450), (50, -450)), ((0, 0), (2000, 0)), ((0, 100), (2000, 100))])  # the stub is read first
    assert [(w.thickness, w.start[0], w.end[0]) for w in walls] == [(100, 0, 2000)]
    found = [i for i in issues if i.code == "ambiguous_pairing_resolved"]
    assert found and any("left unpaired" in i.message for i in found)
    assert not [i for i in issues if i.severity == "blocking"]


def test_equally_strong_competing_partners_stay_blocking():
    # existing rule, with partners sharing the same long stretch: no rule picks one
    _, _, issues = run([((0, 0), (2000, 0)), ((0, 200), (2000, 200)), ((0, 400), (2000, 400))])
    assert {i.code for i in issues if i.severity == "blocking"} == {"ambiguous_pairing"}


def test_stray_line_between_partners_too_far_apart_to_be_a_wall_stays_blocking():
    # the long lines 800 mm apart cannot pair with each other (max wall thickness 600), so they do not
    # make the 50 mm stub between them a stray line beside a wall: no rule picks one
    _, _, issues = run([((0, 0), (50, 0)), ((0, -400), (2000, -400)), ((0, 400), (2000, 400))])
    assert {i.code for i in issues if i.severity == "blocking"} == {"ambiguous_pairing"}


def _walls_and_codes(lines):
    walls, _, issues = run(lines)
    return walls, [i.code for i in issues if i.severity == "blocking"], [i for i in issues if i.code == "short_cross_pair_ignored"]


def test_end_cap_pair_over_a_real_wall_is_not_a_chunky_second_wall():
    # a wall (faces y=0 and y=150, x 150..550) with a 150 mm cap line at both ends of a 550 mm stretch: the two
    # caps are 550 apart but only 150 long, and would make a 550 x 150 block that swallows the real wall
    walls, blocking, notes = _walls_and_codes([
        ((0, 0), (550, 0)), ((150, 150), (550, 150)), ((0, 0), (0, 150)), ((550, 0), (550, 150)),
    ])
    assert [(w.thickness, w.start, w.end) for w in walls] == [(150, (150, 75), (550, 75))]
    assert not blocking and len(notes) == 1 and notes[0].severity == "warning"
    assert {s.entity_handle for s in notes[0].sources} == {"H0", "H1", "H2", "H3"}


def test_closed_box_is_one_wall_along_its_longer_side():
    # 300 x 200 box drawn as four lines (a pier on the wall layer): it paired both ways before, two walls on one footprint
    walls, blocking, notes = _walls_and_codes([
        ((0, 0), (300, 0)), ((0, 200), (300, 200)), ((0, 0), (0, 200)), ((300, 0), (300, 200)),
    ])
    assert [(w.thickness, w.start, w.end) for w in walls] == [(200, (0, 100), (300, 100))]
    assert not blocking and len(notes) == 1


def test_square_box_keeps_one_pair_and_a_short_legit_wall_is_kept():
    walls, _, notes = _walls_and_codes([
        ((0, 0), (200, 0)), ((0, 200), (200, 200)), ((0, 0), (0, 200)), ((200, 0), (200, 200)),
    ])
    assert len(walls) == 1 and len(notes) == 1  # a square has no longer side: one footprint, once
    # a short wall that swallows nothing is still a wall (100 mm of wall beside a window, say)
    walls, _, notes = _walls_and_codes([((0, 0), (100, 0)), ((0, 200), (100, 200))])
    assert [(w.thickness, w.start, w.end) for w in walls] == [(200, (0, 100), (100, 100))] and not notes


def test_pier_drawn_by_its_short_sides_is_kept_and_flagged_not_dropped():
    # a 300 x 200 pier drawn as its two 200 mm sides; a 100 mm wall pair lies inside it but does not cover it
    walls, _, issues = run([
        ((0, 0), (0, 200)), ((300, 0), (300, 200)), ((0, 50), (300, 50)), ((0, 150), (300, 150)),
    ])
    assert len(walls) == 2  # the inner wall and the pier itself: nothing silently dropped
    assert [i.code for i in issues if i.code.startswith("short_cross_pair")] == ["short_cross_pair_unexplained"]
    assert {(w.thickness, w.start[0], w.end[0]) for w in walls} == {(100, 0, 300), (300, 150, 150)}


def test_identical_cross_pairs_are_kept_once():
    from api.engine.geometry2d.walls import _one_wall_per_box

    s = [Segment(f"S{n}", "A-WALL", (0, 0), (0, 1)) for n in range(4)]
    raw = [((150.0, 0.0), (150.0, 200.0), 300.0, (s[0], s[1])), ((150.0, 0.0), (150.0, 200.0), 300.0, (s[2], s[3]))]
    kept, issues = _one_wall_per_box(raw, 1e-6)
    assert kept == raw[:1] and [i.code for i in issues] == ["short_cross_pair_unexplained", "short_cross_pair_ignored"]


def test_loose_line_that_is_not_a_wall_end_cap_stays_unpaired():
    # a 200 mm cap at the wall's end is consumed; a 150 mm line there (not the full thickness) and a line far from any wall are not
    walls, _, issues = run([
        ((0, 0), (1000, 0)), ((0, 200), (1000, 200)),
        ((1000, 0), (1000, 200)),  # full-thickness cap at the end
        ((0, 0), (0, 150)),  # at the end but not the thickness
        ((5000, 5000), (5000, 5200)),  # across a thickness but nowhere near a wall
    ])
    assert len(walls) == 1
    assert [i.code for i in issues] == ["unpaired_segment", "unpaired_segment", "wall_end_caps_consumed"]
    assert [s.entity_handle for s in [i for i in issues if i.code == "wall_end_caps_consumed"][0].sources] == ["H2"]
