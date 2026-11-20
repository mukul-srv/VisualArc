"""ADR-002 T11 acceptance tests 1-13 (opening detection in the DXF reader).

Expected values come from the ADR worked example and the drawing coordinates
each test writes, never from reader output.
"""

import json
from collections import Counter
from pathlib import Path

import ezdxf
import pytest

from api.cli import main
from api.engine.adapters.dxf.reader import read_dxf

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


class Drawing:
    """mm DXF builder that remembers handles by name."""

    def __init__(self, insunits: int = 4, case=str.upper):
        self.doc = ezdxf.new("R2018", setup=False)
        self.doc.header["$INSUNITS"] = insunits
        self.msp = self.doc.modelspace()
        self.case = case
        self.h: dict[str, str] = {}

    def line(self, name, a, b, layer="A-WALL"):
        e = self.msp.add_line(a, b, dxfattribs={"layer": self.case(layer)})
        self.h[name] = e.dxf.handle

    def rect(self, name, x0, y0, x1, y1, layer):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        e = self.msp.add_lwpolyline(
            pts, close=True, dxfattribs={"layer": self.case(layer)}
        )
        self.h[name] = e.dxf.handle

    def save(self, tmp_path: Path, name="t.dxf") -> Path:
        path = tmp_path / name
        self.doc.saveas(path)
        return path


def worked_example(d: Drawing, glaz_marker=True) -> Drawing:
    """ADR-002 'Worked example', entity for entity."""
    for n, a, b in [
        ("b1", (0, 0), (1000, 0)),
        ("b2", (1900, 0), (3000, 0)),
        ("b3", (3600, 0), (5000, 0)),
        ("t1", (0, 200), (1000, 200)),
        ("t2", (1900, 200), (3000, 200)),
        ("t3", (3600, 200), (5000, 200)),
        ("e0", (0, 0), (0, 200)),
        ("e1", (5000, 0), (5000, 200)),
        ("j1", (1000, 0), (1000, 200)),
        ("j2", (1900, 0), (1900, 200)),
        ("j3", (3000, 0), (3000, 200)),
        ("j4", (3600, 0), (3600, 200)),
    ]:
        d.line(n, a, b)
    d.rect("D1", 1000, 0, 1900, 200, "A-DOOR")
    arc = d.msp.add_arc((1000, 200), 900, 0, 90, dxfattribs={"layer": d.case("A-DOOR")})
    d.h["S1"] = arc.dxf.handle
    d.line("L1", (1000, 200), (1000, 1100), "A-DOOR")
    if glaz_marker:
        d.rect("G1", 3000, 0, 3600, 200, "A-GLAZ")
    d.line("g1", (3000, 100), (3600, 100), "A-GLAZ")
    return d


def _floor(p):
    return p.buildings[0].floors[0]


def _codes(p, severity=None):
    return Counter(i.code for i in p.issues if severity in (None, i.severity))


def _issue(p, code):
    (i,) = [i for i in p.issues if i.code == code]
    return i


def _handles(refs):
    return [r.entity_handle for r in refs]


# --- 1. worked example -------------------------------------------------------


def test_1_worked_example_exact_values(tmp_path):
    d = worked_example(Drawing())
    p = read_dxf(d.save(tmp_path), wall_height=2700)
    f, h = _floor(p), d.h

    (w,) = f.walls
    assert w.id == "wall-001"
    assert (w.centreline.start, w.centreline.end) == ((0, 100), (5000, 100))
    assert (w.thickness.value, w.thickness.source) == (200, "source_extracted")
    assert (w.height.value, w.height.source) == (2700, "user_provided")
    assert sorted(_handles(w.sources)) == sorted(
        h[n] for n in ("b1", "b2", "b3", "t1", "t2", "t3")
    )

    door, window = f.openings
    expect = [
        (door, "opening-001", "door", (1000, 100), (1900, 100), 1000, 900, 2100, 0,
         ["D1", "j1", "j2"]),
        (window, "opening-002", "window", (3000, 100), (3600, 100), 3000, 600, 1200,
         900, ["G1", "j3", "j4"]),
    ]  # fmt: skip
    for o, oid, kind, s, e, off, width, height, sill, srcs in expect:
        assert (o.id, o.kind, o.wall_id) == (oid, kind, "wall-001")
        assert (o.span.start, o.span.end) == (s, e)
        assert (o.offset.value, o.offset.source) == (off, "source_extracted")
        assert (o.width.value, o.width.source) == (width, "source_extracted")
        assert (o.height.value, o.height.source) == (height, "defaulted")
        assert (o.sill_height.value, o.sill_height.source) == (sill, "defaulted")
        assert _handles(o.sources) == [h[n] for n in srcs]
        assert o.sources[0].layer == ("A-DOOR" if kind == "door" else "A-GLAZ")

    assert _codes(p) == {
        "opening_dimension_defaulted": 2,
        "opening_symbol_ignored": 2,
        "unpaired_segment": 2,
        "elevation_defaulted": 1,
    }
    assert not _codes(p, "blocking")
    unpaired = [i for i in p.issues if i.code == "unpaired_segment"]
    assert sorted(_handles(r for i in unpaired for r in i.sources)) == sorted(
        [h["e0"], h["e1"]]
    )
    sym = {
        i.message.split(":")[0]: i
        for i in p.issues
        if i.code == "opening_symbol_ignored"
    }
    assert "1 ARC, 1 LINE" in sym["opening layer A-DOOR"].message
    assert _handles(sym["opening layer A-DOOR"].sources) == [h["S1"], h["L1"]]
    assert "1 LINE" in sym["opening layer A-GLAZ"].message
    assert not [j for j in f.junctions]
    assert "orphan_door_swing" not in _codes(p)  # S1 is centred on a D1 vertex


# --- 2. jamb consumption (500 mm window) ------------------------------------


def _wall_with_gap(d: Drawing, g0, g1, jambs=True, t=200, length=5000):
    """Horizontal wall 0..length, faces y=0 and y=t, broken at g0..g1, end caps."""
    for n, y in (("b", 0), ("t", t)):
        d.line(f"{n}1", (0, y), (g0, y))
        d.line(f"{n}2", (g1, y), (length, y))
    d.line("e0", (0, 0), (0, t))
    d.line("e1", (length, 0), (length, t))
    if jambs:
        d.line("j1", (g0, 0), (g0, t))
        d.line("j2", (g1, 0), (g1, t))
    return d


def test_2_narrow_window_jambs_consumed_no_plug(tmp_path):
    d = _wall_with_gap(Drawing(), 2000, 2500)
    d.rect("G", 2000, 0, 2500, 200, "A-GLAZ")
    p = read_dxf(d.save(tmp_path), 2700)
    (w,) = _floor(p).walls  # no 500 mm perpendicular plug wall
    assert (w.centreline.start, w.centreline.end) == ((0, 100), (5000, 100))
    (o,) = _floor(p).openings
    assert (o.span.start, o.span.end, o.width.value) == ((2000, 100), (2500, 100), 500)
    assert _handles(o.sources) == [d.h["G"], d.h["j1"], d.h["j2"]]
    assert not _codes(p, "blocking")


def test_2_narrow_jambs_without_marker_block(tmp_path):
    d = _wall_with_gap(Drawing(), 2000, 2500)
    p = read_dxf(d.save(tmp_path), 2700)
    issue = _issue(p, "gap_closed_by_jamb_pair")
    assert issue.severity == "blocking"
    assert {d.h["j1"], d.h["j2"]} <= set(_handles(issue.sources))
    assert not _floor(p).openings


# --- 3. exact matching only --------------------------------------------------

GAP = (1000, 0, 1900, 200)
GAP_PTS = [(1000, 0), (1900, 0), (1900, 200), (1000, 200)]


@pytest.mark.parametrize(
    "marker",
    [
        (1000, 0, 1899.99, 200),  # narrower
        (1000, 0.01, 1900, 200),  # thinner
        (1000, 0.01, 1900, 200.01),  # offset across the wall
        (1000, 0, 1900, 200.01),  # thicker
    ],
)
def test_3_marker_mismatch(tmp_path, marker):
    d = _wall_with_gap(Drawing(), 1000, 1900, jambs=False)
    d.rect("M", *marker, "A-DOOR")
    p = read_dxf(d.save(tmp_path), 2700)
    issue = _issue(p, "opening_marker_mismatch")
    assert issue.severity == "blocking" and d.h["M"] in _handles(issue.sources)
    assert "+0.01 mm" in issue.message or "-0.01 mm" in issue.message
    assert not _floor(p).openings and len(_floor(p).walls) == 2


@pytest.mark.parametrize(
    "marker",
    [(999.99, 0, 1900, 200), (1000.01, 0, 1900.01, 200)],  # wider; offset along wall
)
def test_3_marker_overlapping_wall_is_blocking(tmp_path, marker):
    # ADR-002 ambiguity: test 3 lists wider/offset as mismatch, while §4.3/§9 say a
    # marker overlapping wall material is opening_marker_without_gap. The reader
    # follows §4.3 order (material first). Either way: blocking, no opening.
    d = _wall_with_gap(Drawing(), 1000, 1900, jambs=False)
    d.rect("M", *marker, "A-DOOR")
    p = read_dxf(d.save(tmp_path), 2700)
    assert _codes(p, "blocking") == {"opening_marker_without_gap": 1}
    assert not _floor(p).openings and len(_floor(p).walls) == 2


# --- 4. association failures --------------------------------------------------


def test_4_marker_on_unbroken_wall(tmp_path):
    d = Drawing()
    d.line("b", (0, 0), (5000, 0))
    d.line("t", (0, 200), (5000, 200))
    d.rect("M", 1000, 0, 1900, 200, "A-DOOR")
    p = read_dxf(d.save(tmp_path), 2700)
    assert _issue(p, "opening_marker_without_gap").severity == "blocking"
    assert len(_floor(p).walls) == 1 and not _floor(p).openings


def test_4_marker_in_free_space(tmp_path):
    d = _wall_with_gap(Drawing(), 1000, 1900, jambs=False)
    d.rect("M", 1000, 3000, 1900, 3200, "A-GLAZ")
    p = read_dxf(d.save(tmp_path), 2700)
    assert _issue(p, "opening_marker_outside_wall").severity == "blocking"
    assert "unmarked_wall_gap" in _codes(p)


def test_4_marker_over_two_gaps(tmp_path):
    d = Drawing()
    for y in (0, 200):
        for x0, x1 in ((0, 1000), (1900, 3000), (3600, 5000)):
            d.line(f"{x0}-{y}", (x0, y), (x1, y))
    d.rect("M", 1000, 0, 3600, 200, "A-GLAZ")
    p = read_dxf(d.save(tmp_path), 2700)
    assert _codes(p, "blocking") == {"opening_spans_multiple_gaps": 1}
    assert len(_floor(p).walls) == 3 and not _floor(p).openings


# --- 5-8. gap checks ----------------------------------------------------------


def test_5_door_and_window_on_one_gap(tmp_path):
    d = _wall_with_gap(Drawing(), 1000, 1900)
    d.rect("D", *GAP, "A-DOOR")
    d.rect("W", *GAP, "A-GLAZ")
    p = read_dxf(d.save(tmp_path), 2700)
    issue = _issue(p, "multiple_opening_markers")
    assert issue.severity == "blocking"
    assert {d.h["D"], d.h["W"]} <= set(_handles(issue.sources))
    assert len(_floor(p).walls) == 2 and not _floor(p).openings


def test_6_flanking_walls_differ_in_thickness(tmp_path):
    d = Drawing()
    d.line("a0", (0, 0), (1000, 0))
    d.line("a1", (0, 200), (1000, 200))
    d.line("b0", (1900, 0), (3000, 0))
    d.line("b1", (1900, 150), (3000, 150))
    d.rect("M", *GAP, "A-DOOR")
    p = read_dxf(d.save(tmp_path), 2700)
    assert _codes(p, "blocking") == {"opening_host_mismatch": 1}
    assert not _floor(p).openings


@pytest.mark.parametrize("marked", [False, True])
def test_7_one_face_continuous(tmp_path, marked):
    d = Drawing()
    d.line("long", (0, 0), (5000, 0))
    d.line("t1", (0, 200), (1000, 200))
    d.line("t2", (1900, 200), (5000, 200))
    if marked:
        d.rect("M", *GAP, "A-DOOR")
    p = read_dxf(d.save(tmp_path), 2700)
    issue = _issue(p, "partial_wall_gap")
    assert issue.severity == "blocking" and d.h["long"] in _handles(issue.sources)
    assert not _floor(p).openings and len(_floor(p).walls) == 2
    assert ("unmarked_wall_gap" in _codes(p)) is not marked


def test_7_wall_line_on_marker_long_edge_is_not_a_jamb(tmp_path):
    # a face line exactly on the marker's long edge runs across the gap: it is
    # restored to pairing (only edges perpendicular to the host are jambs)
    d = _wall_with_gap(Drawing(), 1000, 1900)
    d.line("across", (1000, 0), (1900, 0))
    d.rect("M", *GAP, "A-DOOR")
    p = read_dxf(d.save(tmp_path), 2700)
    assert _codes(p, "blocking")
    assert not _floor(p).openings


def test_8_unmarked_gap_is_a_warning(tmp_path):
    d = _wall_with_gap(Drawing(), 1000, 1900, jambs=False)
    p = read_dxf(d.save(tmp_path), 2700)
    issue = _issue(p, "unmarked_wall_gap")
    assert issue.severity == "warning" and not _codes(p, "blocking")
    assert len(_floor(p).walls) == 2 and not _floor(p).openings
    assert set(_handles(issue.sources)) == {d.h[n] for n in ("b1", "t1", "b2", "t2")}


# --- 9-10. opening-layer entities ---------------------------------------------


def test_9_insert_on_door_layer(tmp_path):
    d = _wall_with_gap(Drawing(), 1000, 1900, jambs=False)
    d.doc.blocks.new("DOOR")
    e = d.msp.add_blockref("DOOR", (1000, 0), dxfattribs={"layer": "A-DOOR"})
    p = read_dxf(d.save(tmp_path), 2700)
    issue = _issue(p, "unsupported_opening_block")
    assert issue.severity == "blocking" and _handles(issue.sources) == [e.dxf.handle]
    assert "unmapped_layer" not in _codes(p)


@pytest.mark.parametrize(
    "pts, kw",
    [
        ([(1000, 0), (1900, 10), (1890, 210), (990, 200)], {}),  # rotated
        ([(1000, 0, 0, 0, 0.5), (1900, 0), (1900, 200), (1000, 200)], {}),  # bulge
        ([(1000, 0), (1900, 0), (1000, 200)], {}),  # 3 vertices
        ([(1000, 0), (1450, 0), (1900, 0), (1900, 200), (1000, 200)], {}),  # 5
        (GAP_PTS, {"extrusion": (0.1, 0, 0.995)}),  # tilted
    ],
)  # fmt: skip
def test_9_invalid_marker(tmp_path, pts, kw):
    d = _wall_with_gap(Drawing(), 1000, 1900, jambs=False)
    e = d.msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-GLAZ", **kw})
    p = read_dxf(d.save(tmp_path), 2700)
    issue = _issue(p, "invalid_opening_marker")
    assert issue.severity == "blocking" and _handles(issue.sources) == [e.dxf.handle]
    assert not _floor(p).openings


def test_9_marker_closed_by_repeated_vertex_is_valid(tmp_path):
    d = _wall_with_gap(Drawing(), 1000, 1900, jambs=False)
    d.msp.add_lwpolyline(GAP_PTS + GAP_PTS[:1], dxfattribs={"layer": "A-DOOR"})
    (o,) = _floor(read_dxf(d.save(tmp_path), 2700)).openings
    assert o.width.value == 900


def test_10_orphan_swing_and_symbols_never_geometry(tmp_path):
    plain = _wall_with_gap(Drawing(), 1000, 1900)
    plain.rect("D", *GAP, "A-DOOR")
    ref = read_dxf(plain.save(tmp_path, "plain.dxf"), 2700)

    d = _wall_with_gap(Drawing(), 1000, 1900)
    d.rect("D", *GAP, "A-DOOR")
    arc = d.msp.add_arc((8000, 8000), 900, 0, 90, dxfattribs={"layer": "A-DOOR"})
    ok_arc = d.msp.add_arc((1000, 200), 900, 0, 90, dxfattribs={"layer": "A-DOOR"})
    d.line("leaf", (1000, 200), (1000, 1100), "A-DOOR")
    d.msp.add_circle((1450, 100), 50, dxfattribs={"layer": "A-DOOR"})
    d.msp.add_text("D01", dxfattribs={"layer": "A-DOOR"})
    d.msp.add_lwpolyline([(0, 0), (500, 500)], dxfattribs={"layer": "A-DOOR"})
    d.line("glass", (1000, 100), (1900, 100), "A-GLAZ")
    p = read_dxf(d.save(tmp_path), 2700)

    orphan = _issue(p, "orphan_door_swing")
    assert orphan.severity == "warning"
    assert _handles(orphan.sources) == [arc.dxf.handle] != [ok_arc.dxf.handle]
    msgs = {
        i.sources[0].layer: i.message
        for i in p.issues
        if i.code == "opening_symbol_ignored"
    }
    assert "2 ARC, 1 CIRCLE, 1 LINE, 1 LWPOLYLINE, 1 TEXT" in msgs["A-DOOR"]
    assert "1 LINE" in msgs["A-GLAZ"]
    for got, want in zip(_floor(p).walls + _floor(p).openings,
                         _floor(ref).walls + _floor(ref).openings, strict=True):  # fmt: skip
        assert got.model_dump(exclude={"sources"}) == want.model_dump(
            exclude={"sources"}
        )


def test_10_symbol_refs_capped(tmp_path):
    d = Drawing()
    for k in range(25):
        d.line(f"s{k}", (0, 5000 + k), (100, 5000 + k), "A-GLAZ")
    issue = _issue(read_dxf(d.save(tmp_path), 2700), "opening_symbol_ignored")
    assert "25 LINE" in issue.message and "first 20 of 25" in issue.message
    assert _handles(issue.sources) == [d.h[f"s{k}"] for k in range(20)]


# --- 11. heights and sills ------------------------------------------------------


def test_11_window_exceeds_wall_height(tmp_path):
    path = worked_example(Drawing()).save(tmp_path)
    out = tmp_path / "o.json"
    with pytest.raises(SystemExit) as exc:
        main(["interpret", str(path), "--wall-height", "2700", "--window-sill", "1800",
              "--window-height", "1200", "--out", str(out)])  # fmt: skip
    assert exc.value.code == 1
    p = json.loads(out.read_text())
    (issue,) = [i for i in p["issues"] if i["code"] == "opening_exceeds_wall_height"]
    assert issue["severity"] == "blocking"
    assert [o["kind"] for o in p["buildings"][0]["floors"][0]["openings"]] == ["door"]


def test_11_flags_are_user_provided(tmp_path):
    path = worked_example(Drawing()).save(tmp_path)
    p = read_dxf(path, 2700, door_height=2000, window_height=1000, window_sill=600)
    door, window = _floor(p).openings
    assert (door.height.value, door.height.source) == (2000, "user_provided")
    assert (door.sill_height.value, door.sill_height.source) == (0, "defaulted")
    assert (window.height.value, window.height.source) == (1000, "user_provided")
    assert (window.sill_height.value, window.sill_height.source) == (
        600,
        "user_provided",
    )
    (issue,) = [i for i in p.issues if i.code == "opening_dimension_defaulted"]
    assert "door" in issue.message and "sill 0 mm" in issue.message
    assert "height" not in issue.message


def test_11_equal_to_wall_height_is_allowed(tmp_path):
    path = worked_example(Drawing()).save(tmp_path)
    p = read_dxf(path, 2700, window_height=1800, window_sill=900)
    assert len(_floor(p).openings) == 2 and not _codes(p, "blocking")


@pytest.mark.parametrize(
    "flag, value",
    [("--door-height", "0"), ("--window-height", "-1"), ("--window-sill", "-0.5")],
)
def test_11_cli_rejects_bad_flags(tmp_path, flag, value):
    path = worked_example(Drawing()).save(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["interpret", str(path), "--wall-height", "2700", flag, value])
    assert exc.value.code == 2


def test_11_reader_rejects_bad_values(tmp_path):
    path = worked_example(Drawing()).save(tmp_path)
    for kw in ({"door_height": 0}, {"window_height": -1}, {"window_sill": -1}):
        with pytest.raises(ValueError):
            read_dxf(path, 2700, **kw)


def test_11_window_sill_zero_accepted_by_cli(tmp_path):
    path = worked_example(Drawing()).save(tmp_path)
    out = tmp_path / "o.json"
    main(["interpret", str(path), "--wall-height", "2700", "--window-sill", "0",
          "--out", str(out)])  # fmt: skip
    (_, w) = json.loads(out.read_text())["buildings"][0]["floors"][0]["openings"]
    assert w["sill_height"] == {"value": 0.0, "unit": "mm", "source": "user_provided"}


# --- 12-13. layer case, units ---------------------------------------------------


def test_12_lower_case_layers_identical(tmp_path):
    (tmp_path / "u").mkdir()
    upper = read_dxf(worked_example(Drawing()).save(tmp_path / "u"), 2700)
    lower = read_dxf(worked_example(Drawing(case=str.lower)).save(tmp_path), 2700)
    dump = lambda p: json.loads(p.model_dump_json().upper())
    assert dump(lower) == dump(upper)
    assert _floor(lower).openings[0].sources[0].layer == "a-door"


def test_13_units_flag_makes_width_and_offset_user_provided(tmp_path):
    d = worked_example(Drawing(insunits=0))
    p = read_dxf(d.save(tmp_path), 2700, user_units="mm")
    for o in _floor(p).openings:
        assert o.width.source == o.offset.source == "user_provided"
    assert [o.width.value for o in _floor(p).openings] == [900, 600]


def test_13_units_scale_openings(tmp_path):
    d = Drawing(insunits=6)  # metres
    for n, y in (("b", 0), ("t", 0.2)):
        d.line(f"{n}1", (0, y), (1, y))
        d.line(f"{n}2", (1.9, y), (5, y))
    d.rect("D", 1, 0, 1.9, 0.2, "A-DOOR")
    (o,) = _floor(read_dxf(d.save(tmp_path), 2700)).openings
    assert o.width.value == pytest.approx(900, abs=1e-6)
    assert o.offset.value == pytest.approx(1000, abs=1e-6)
    assert o.width.source == "source_extracted"
