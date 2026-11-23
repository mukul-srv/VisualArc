"""Real third-party drawings (fixtures/local, never committed): the reader must not stop on the things
real files do (overlapping duplicate lines, door/window blocks, a wrong units header). Skipped when the
files are absent. Expected values are properties of the rules, not of the files' coordinates."""

from pathlib import Path

import ezdxf
import pytest

from api.engine.adapters.dxf.reader import read_dxf
from api.engine.adapters.dxf.split import FloorScope, detect_floors

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
LOCAL = FIXTURES / "local"
HOUSE = FIXTURES / "input" / "Two-story-house-410202.dxf"
SHEET = FIXTURES / "input" / "fp1344-1535.dxf"
KW = {"wall_height": 2700, "ceiling_height": 2700}


def _blocking(p):
    return {i.code for i in p.issues if i.severity == "blocking"}


@pytest.mark.skipif(not LOCAL.is_dir(), reason="fixtures/local not present")
@pytest.mark.parametrize("name", ["cadcraft-sample-house", "draftcraft-apartment", "villa-gf", "villa-ff"])
def test_duplicate_lines_and_blocks_no_longer_block(name):
    path = LOCAL / f"{name}.dxf"
    if not path.is_file():
        pytest.skip(f"{path.name} not present")
    p = read_dxf(path, **KW)
    assert not _blocking(p) & {"overlapping_wall_lines", "unsupported_opening_block"}
    assert p.buildings and p.buildings[0].floors[0].walls


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


@pytest.mark.skipif(not SHEET.is_file(), reason="title sheet not present")
def test_title_sheet_is_not_a_plan():
    codes = [i.code for i in read_dxf(SHEET, **KW).issues]
    assert codes[:1] == ["no_plan_geometry"] and "units_missing" in codes
