"""Rooms: closed regions from the wall graph, named by TEXT/MTEXT (Phase 1/08)."""

from pathlib import Path

import ezdxf
import pytest

from api.engine.adapters.dxf.reader import read_dxf

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
OUTER = [(0, 0), (4400, 0), (4400, 3400), (0, 3400)]  # 200 mm walls: clear room 4000 x 3000
INNER = [(200, 200), (4200, 200), (4200, 3200), (200, 3200)]


def _box(tmp_path, labels=(), skip_top=False, extra=(), shift=0):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for loop in (OUTER, INNER):
        loop = [(x + shift, y) for x, y in loop]
        for i, a in enumerate(loop):
            b = loop[(i + 1) % 4]
            if skip_top and a[1] == b[1] == max(y for _, y in loop):
                continue
            msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    for a, b in extra:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    for kind, text, at in labels:
        if kind == "TEXT":
            msp.add_text(text, dxfattribs={"layer": "A-ANNO-TEXT", "insert": at})
        else:
            msp.add_mtext(text, dxfattribs={"layer": "A-ANNO-TEXT", "insert": at})
    path = tmp_path / "box.dxf"
    doc.saveas(path)
    return read_dxf(path, 3000, ceiling_height=3000)


def _codes(p):
    return {i.code for i in p.issues}


def test_area_matches_hand_calculation_on_fixture_b():
    # L-shaped clear room: 5600 x 2600 + 2600 x 2000 mm (make_fixture_b docstring)
    (room,) = read_dxf(INPUT / "fixture_b.dxf", 3000, ceiling_height=3000).buildings[0].floors[0].rooms
    assert room.area.value == pytest.approx(5600 * 2600 + 2600 * 2000)
    assert (room.area.unit, room.area.source) == ("mm2", "inferred")
    assert (room.name, room.name_source) == ("Room 1", "defaulted")


def test_one_label_names_the_room(tmp_path):
    p = _box(tmp_path, [("TEXT", "Kitchen", (1000, 1000))])
    (room,) = p.buildings[0].floors[0].rooms
    assert (room.name, room.name_source) == ("Kitchen", "source_extracted")
    assert room.area.value == pytest.approx(4000 * 3000)
    assert len(room.label_sources) == 1
    assert not _codes(p) & {"room_name_defaulted", "room_name_ambiguous", "room_label_unplaced"}


def test_no_label_is_numbered_with_an_info_issue(tmp_path):
    p = _box(tmp_path)
    assert p.buildings[0].floors[0].rooms[0].name == "Room 1"
    assert "room_name_defaulted" in _codes(p)


def test_several_labels_take_first_in_reading_order_and_warn_with_all(tmp_path):
    # "Lower" is first in the file and further left, but "Upper" is higher on the plan
    p = _box(tmp_path, [("TEXT", "Lower", (500, 600)), ("MTEXT", "Upper", (2500, 2500))])
    (room,) = p.buildings[0].floors[0].rooms
    assert room.name == "Upper" and len(room.label_sources) == 2
    (issue,) = [i for i in p.issues if i.code == "room_name_ambiguous"]
    assert issue.severity == "warning" and "Lower" in issue.message and "Upper" in issue.message


def test_label_outside_and_unclosed_walls_are_reported(tmp_path):
    p = _box(tmp_path, [("TEXT", "Garden", (9000, 9000))])
    assert "room_label_unplaced" in _codes(p)
    p = _box(tmp_path, [("TEXT", "Hall", (1000, 1000))], skip_top=True)
    assert not p.buildings[0].floors[0].rooms
    assert {"no_closed_rooms", "room_label_unplaced"} <= _codes(p)


def test_open_outline_is_reported_even_when_another_room_closes(tmp_path):
    # a closed box, plus a second box (no label inside it) with its top wall missing
    closed = _box(tmp_path, [("TEXT", "Hall", (1000, 1000))])
    assert "room_outline_open" not in _codes(closed)
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for shift, skip in ((0, False), (6000, True)):
        for loop in (OUTER, INNER):
            loop = [(x + shift, y) for x, y in loop]
            for i, a in enumerate(loop):
                b = loop[(i + 1) % 4]
                if not (skip and a[1] == b[1] == max(y for _, y in loop)):
                    msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    doc.saveas(tmp_path / "two.dxf")
    p = read_dxf(tmp_path / "two.dxf", 3000, ceiling_height=3000)
    assert len(p.buildings[0].floors[0].rooms) == 1  # only the closed one
    (issue,) = [i for i in p.issues if i.code == "room_outline_open"]
    assert issue.severity == "warning" and issue.sources
    assert "no_closed_rooms" not in _codes(p)


def test_obstruction_keeps_polygon_and_area_consistent(tmp_path):
    # a free-standing 1000 x 200 wall piece inside the 4000 x 3000 room
    p = _box(tmp_path, extra=[((1000, 1000), (2000, 1000)), ((1000, 1200), (2000, 1200))])
    (room,) = p.buildings[0].floors[0].rooms
    assert len(room.holes) == 1
    assert room.area.value == pytest.approx(4000 * 3000 - 1000 * 200)
    assert "room_has_obstruction" in _codes(p)


def test_labels_without_walls_are_reported(tmp_path):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    doc.modelspace().add_text("Lost", dxfattribs={"layer": "A-ANNO-TEXT", "insert": (0, 0)})
    doc.saveas(tmp_path / "t.dxf")
    p = read_dxf(tmp_path / "t.dxf", 3000, ceiling_height=3000)
    assert {"no_walls", "rooms_not_built"} <= _codes(p)
