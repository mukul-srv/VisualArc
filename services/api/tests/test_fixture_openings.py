"""Checks the generated openings fixture itself, then the reader output (T11)."""

import json
from collections import Counter
from pathlib import Path

import ezdxf
import pytest

DXF = (
    Path(__file__).resolve().parents[3] / "fixtures" / "input" / "fixture_openings.dxf"
)

# (layer, axis, (x0, y0, x1, y1) of the marker) from the documented table in scripts/make_fixture_openings.py
MARKERS = [
    ("A-GLAZ", (1200, 0, 1700, 200)),
    ("A-GLAZ", (4400, 0, 5600, 200)),
    ("A-DOOR", (7500, 0, 8400, 200)),
    ("A-DOOR", (3200, 1000, 3300, 1900)),
    ("A-GLAZ", (0, 1500, 200, 2400)),
    ("A-GLAZ", (9400, 1500, 9600, 2700)),
    ("A-DOOR", (6300, 2000, 6400, 2800)),
]


@pytest.fixture(scope="module")
def msp():
    return ezdxf.readfile(DXF).modelspace()


def test_layer_entity_counts(msp):
    got = Counter((e.dxf.layer, e.dxftype()) for e in msp)
    assert got == {
        ("A-WALL", "LINE"): 36,
        ("A-FLOR", "LWPOLYLINE"): 3,
        ("A-DOOR", "LWPOLYLINE"): 3,
        ("A-DOOR", "ARC"): 3,
        ("A-DOOR", "LINE"): 3,
        ("A-GLAZ", "LWPOLYLINE"): 4,
    }


def test_markers_match_table(msp):
    got = []
    for e in msp.query("LWPOLYLINE"):
        if e.dxf.layer not in ("A-DOOR", "A-GLAZ"):
            continue
        pts = [tuple(p[:2]) for p in e.get_points()]
        assert e.closed and len(pts) == 4
        xs, ys = {p[0] for p in pts}, {p[1] for p in pts}
        assert len(xs) == 2 and len(ys) == 2  # axis-aligned rectangle
        got.append((e.dxf.layer, (min(xs), min(ys), max(xs), max(ys))))
    assert sorted(got) == sorted(MARKERS)


def test_markers_exactly_fill_wall_gaps(msp):
    lines = [
        (tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2])
        for e in msp.query("LINE")
        if e.dxf.layer == "A-WALL"
    ]
    for _, (x0, y0, x1, y1) in MARKERS:
        horizontal = (x1 - x0) > (y1 - y0)
        lo, hi = (x0, x1) if horizontal else (y0, y1)
        for c in (
            (y0, y1) if horizontal else (x0, x1)
        ):  # the two face lines of the host wall
            spans = []
            for a, b in lines:
                if horizontal and a[1] == b[1] == c:
                    spans.append(sorted((a[0], b[0])))
                elif not horizontal and a[0] == b[0] == c:
                    spans.append(sorted((a[1], b[1])))
            assert not any(
                s0 < hi and s1 > lo for s0, s1 in spans
            )  # nothing inside the gap
            assert any(s1 == lo for _, s1 in spans) and any(s0 == hi for s0, _ in spans)


# --- T11: reader output, expected values from the generator docstring table ---

# (id, kind, span start, span end, offset, width, has jambs)
OPENINGS = [
    ("opening-001", "window", (1200, 100), (1700, 100), 1000, 500, True),
    ("opening-002", "window", (4400, 100), (5600, 100), 1100, 1200, False),
    ("opening-003", "door", (7500, 100), (8400, 100), 1100, 900, False),
    ("opening-004", "door", (3250, 1000), (3250, 1900), 800, 900, True),
    ("opening-005", "window", (100, 1500), (100, 2400), 1300, 900, False),
    ("opening-006", "window", (9500, 1500), (9500, 2700), 1300, 1200, True),
    ("opening-007", "door", (6350, 2000), (6350, 2800), 1800, 800, False),
]
# host column of the table -> index into WALLS below
HOSTS = {
    "opening-001": 0,  # B1
    "opening-002": 1,  # B2
    "opening-003": 2,  # B3
    "opening-004": 4,  # I1
    "opening-005": 3,  # L
    "opening-006": 6,  # R
    "opening-007": 5,  # I2
}
# merged walls (start, end, thickness), listed in the reader's id sort (start y, x)
WALLS = [
    ((200, 100), (3200, 100), 200),  # B1
    ((3300, 100), (6300, 100), 200),  # B2
    ((6400, 100), (9400, 100), 200),  # B3
    ((100, 200), (100, 3800), 200),  # L
    ((3250, 200), (3250, 3800), 100),  # I1
    ((6350, 200), (6350, 3800), 100),  # I2
    ((9500, 200), (9500, 3800), 200),  # R
    ((200, 3900), (3200, 3900), 200),  # T1
    ((3300, 3900), (6300, 3900), 200),  # T2
    ((6400, 3900), (9400, 3900), 200),  # T3
]


@pytest.fixture(scope="module")
def floor_project():
    from api.engine.adapters.dxf.reader import read_dxf

    return read_dxf(DXF, wall_height=3000)


def test_reader_merges_walls_around_openings(floor_project):
    f = floor_project.buildings[0].floors[0]
    assert [
        (w.centreline.start, w.centreline.end, w.thickness.value) for w in f.walls
    ] == WALLS
    assert all(w.thickness.value != 500 for w in f.walls)  # no jamb plug at opening-001


def test_reader_openings_match_table(floor_project):
    f = floor_project.buildings[0].floors[0]
    walls = {w.id: w for w in f.walls}
    assert len(f.openings) == len(OPENINGS)
    for o, (oid, kind, s, e, off, width, jambs) in zip(
        f.openings, OPENINGS, strict=True
    ):
        assert (o.id, o.kind, o.span.start, o.span.end) == (oid, kind, s, e)
        assert (o.offset.value, o.width.value) == (off, width)
        assert {o.offset.source, o.width.source} == {"source_extracted"}
        host = walls[o.wall_id]
        assert (host.centreline.start, host.centreline.end) == WALLS[HOSTS[oid]][:2]
        h, sill = (2100, 0) if kind == "door" else (1200, 900)
        assert (o.height.value, o.sill_height.value) == (h, sill)
        assert {o.height.source, o.sill_height.source} == {"defaulted"}
        layer = "A-DOOR" if kind == "door" else "A-GLAZ"
        assert o.sources[0].layer == layer
        assert [r.layer for r in o.sources[1:]] == (["A-WALL"] * 2 if jambs else [])


def test_reader_junctions_and_issues(floor_project):
    f = floor_project.buildings[0].floors[0]
    sizes = Counter(
        (max(x for x, _ in j.polygon) - min(x for x, _ in j.polygon),
         max(y for _, y in j.polygon) - min(y for _, y in j.polygon))
        for j in f.junctions
    )  # fmt: skip
    assert sizes == {(200, 200): 4, (100, 200): 4}  # 4 corners, 4 T-junctions
    assert Counter(i.code for i in floor_project.issues) == {
        "opening_symbol_ignored": 1,
        "opening_dimension_defaulted": 2,
        "elevation_defaulted": 1,
    }


def test_snapshot(tmp_path):
    from api.cli import main

    out = tmp_path / "o.json"
    main(["interpret", str(DXF), "--wall-height", "3000", "--out", str(out)])
    expected = DXF.parents[1] / "expected" / "fixture_openings.canonical.json"
    assert json.loads(out.read_text()) == json.loads(expected.read_text())
