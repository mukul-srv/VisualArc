"""Real third-party drawings (fixtures/local, never committed): the reader must not stop on the things
real files do (overlapping duplicate lines, door/window blocks, a wrong units header). Skipped when the
files are absent. Expected values are properties of the rules, not of the files' coordinates."""

from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import box

from api.engine.adapters.dxf.reader import read_dxf
from api.engine.adapters.dxf.split import FloorScope, detect_floors

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
LOCAL = FIXTURES / "local"
HOUSE = FIXTURES / "input" / "Two-story-house-410202.dxf"
SHEET = FIXTURES / "input" / "fp1344-1535.dxf"
KW = {"wall_height": 2700, "ceiling_height": 2700}


def _check_walls_are_walls(floor):
    """Properties of real walls, not of one file: each is at least as long as it is thick, and none lies
    inside another (the chunky cross pairs and duplicate boxes read as extra walls before)."""
    rects = []
    for w in floor.walls:
        (x0, y0), (x1, y1) = w.centreline.start, w.centreline.end
        t = w.thickness.value
        assert ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 >= t - 1e-6, w.id
        h = t / 2
        rects.append(box(min(x0, x1) - (h if y0 != y1 else 0), min(y0, y1) - (h if x0 != x1 else 0),
                         max(x0, x1) + (h if y0 != y1 else 0), max(y0, y1) + (h if x0 != x1 else 0)))
    for i, a in enumerate(rects):
        for j, b in enumerate(rects):
            assert i == j or not a.buffer(1e-6).covers(b), (floor.walls[i].id, floor.walls[j].id)


def _blocking(p):
    return {i.code for i in p.issues if i.severity == "blocking"}


@pytest.mark.skipif(not LOCAL.is_dir(), reason="fixtures/local not present")
@pytest.mark.parametrize("name", ["cadcraft-sample-house", "draftcraft-apartment", "villa-gf", "villa-ff"])
def test_real_drawings_read_without_blocking_issues(name):
    path = LOCAL / f"{name}.dxf"
    if not path.is_file():
        pytest.skip(f"{path.name} not present")
    p = read_dxf(path, **KW)
    assert not _blocking(p)
    assert p.buildings and p.buildings[0].floors[0].walls
    _check_walls_are_walls(p.buildings[0].floors[0])


@pytest.mark.parametrize("name", ["cadcraft-sample-house", "draftcraft-apartment"])
def test_real_drawing_without_a_floor_outline_gets_an_inferred_one_and_its_openings(name):
    path = LOCAL / f"{name}.dxf"
    if not path.is_file():
        pytest.skip(f"{path.name} not present")
    f = read_dxf(path, building_type="residential", **KW).buildings[0].floors[0]
    codes = {i.code for i in read_dxf(path, building_type="residential", **KW).issues}
    assert f.boundaries and f.slabs and f.openings
    assert {"floor_boundary_inferred", "opening_cut_into_wall"} <= codes


@pytest.mark.skipif(not HOUSE.is_file(), reason="house drawing not present")
def test_house_wrong_units_header_is_flagged_and_overridable():
    p = read_dxf(HOUSE, **KW)  # header says inches; the house is metres
    assert "units_implausible" in {i.code for i in p.issues}
    doc = ezdxf.readfile(HOUSE)
    split = detect_floors(doc, 1000.0)  # as metres: the two floors side by side
    assert len(split.candidates) == 2
    for c in split.candidates:
        scope = FloorScope(c.handles, (c.bbox[0], c.bbox[1]))
        f = read_dxf(HOUSE, user_units="m", units_override=True, scope=scope, **KW)
        assert "units_overridden" in {i.code for i in f.issues} and not _blocking(f)
        assert f.buildings[0].floors[0].walls
        _check_walls_are_walls(f.buildings[0].floors[0])


@pytest.mark.skipif(not SHEET.is_file(), reason="title sheet not present")
def test_title_sheet_is_not_a_plan():
    codes = [i.code for i in read_dxf(SHEET, **KW).issues]
    assert codes[:1] == ["no_plan_geometry"] and "units_missing" in codes
