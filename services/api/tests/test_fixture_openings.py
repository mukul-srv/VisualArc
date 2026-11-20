"""Checks the generated openings fixture itself (ezdxf only; no opening detection)."""

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
