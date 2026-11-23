import json
import re
from pathlib import Path

import ezdxf
import pytest

from api.cli import main
from api.engine.adapters.dxf.reader import InputError, read_dxf

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
FIXTURE_A = FIXTURES / "input" / "fixture_a.dxf"


def test_fixture_a_known_dimensions():
    p = read_dxf(FIXTURE_A, wall_height=3000, ceiling_height=3000)
    assert [(i.code, i.severity) for i in p.issues] == [
        ("elevation_defaulted", "warning"),
        ("wall_role_inferred", "warning"),
        ("room_name_defaulted", "warning"),
        ("roof_type_unknown", "warning"),
    ]
    assert p.buildings[0].floors[0].elevation.source == "defaulted"
    f = p.buildings[0].floors[0]
    assert sorted(w.thickness.value for w in f.walls) == [100] + [200] * 6
    assert {w.thickness.source for w in f.walls} == {"source_extracted"}
    assert {(w.height.value, w.height.source) for w in f.walls} == {
        (3000, "user_provided")
    }
    assert all(len(w.sources) == 2 for w in f.walls)
    sizes = sorted(
        (
            max(x for x, _ in j.polygon) - min(x for x, _ in j.polygon),
            max(y for _, y in j.polygon) - min(y for _, y in j.polygon),
        )
        for j in f.junctions
    )
    assert sizes == [(100, 200)] * 2 + [(200, 200)] * 4
    assert {j.source for j in f.junctions} == {"inferred"}
    assert [b.polygon for b in f.boundaries] == [
        [(200, 200), (4200, 200), (4200, 5000), (200, 5000)],
        [(4300, 200), (8000, 200), (8000, 5000), (4300, 5000)],
    ]


def test_fixture_a_snapshot(tmp_path: Path):
    out = tmp_path / "a.json"
    main(["interpret", str(FIXTURE_A), "--wall-height", "3000", "--ceiling-height", "3000", "--out", str(out)])
    expected = json.loads(
        (FIXTURES / "expected" / "fixture_a.canonical.json").read_text()
    )
    assert json.loads(out.read_text()) == expected


def test_missing_height_is_blocking_and_cli_fails(tmp_path: Path):
    p = read_dxf(FIXTURE_A)
    assert [(i.code, i.severity) for i in p.issues] == [
        ("wall_height_missing", "blocking"),
        ("elevation_defaulted", "warning"),
        ("wall_role_inferred", "warning"),
        ("ceiling_height_missing", "blocking"),
        ("room_name_defaulted", "warning"),
        ("roof_type_unknown", "warning"),
    ]
    assert all(w.height is None for w in p.buildings[0].floors[0].walls)
    with pytest.raises(SystemExit) as exc:
        main(["interpret", str(FIXTURE_A), "--out", str(tmp_path / "a.json")])
    assert exc.value.code == 1


def _dxf(tmp_path: Path, insunits: int, lines) -> Path:
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = insunits
    for a, b in lines:
        doc.modelspace().add_line(a, b, dxfattribs={"layer": "A-WALL"})
    path = tmp_path / "t.dxf"
    doc.saveas(path)
    return path


def test_unitless_dxf_is_blocking_with_no_geometry(tmp_path: Path):
    p = read_dxf(_dxf(tmp_path, 0, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))]), 3000, ceiling_height=3000)
    assert [i.code for i in p.issues] == ["units_missing"] and p.buildings == []


def test_metre_dxf_converted_to_mm(tmp_path: Path):
    p = read_dxf(_dxf(tmp_path, 6, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))]), 3000, ceiling_height=3000)
    (w,) = p.buildings[0].floors[0].walls
    assert w.thickness.value == pytest.approx(200, abs=1e-6)
    assert w.centreline.end == pytest.approx((1000, 100), abs=1e-6)


def _plan(tmp_path: Path, floor=None, extra=()) -> tuple[Path, dict]:
    """mm DXF: one valid 200 mm wall, optional closed A-FLOR ring, extra entities."""
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in [((0, 0), (4000, 0)), ((0, 200), (4000, 200))]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    handles = {}
    if floor:
        fl = msp.add_lwpolyline(floor, close=True, dxfattribs={"layer": "A-FLOR"})
        handles["floor"] = fl.dxf.handle
    for layer, add in extra:
        handles.setdefault(layer, []).append(add(msp, layer).dxf.handle)
    path = tmp_path / "t.dxf"
    doc.saveas(path)
    return path, handles


def _line(msp, layer):
    return msp.add_line((0, 5000), (100, 5000), dxfattribs={"layer": layer})


def _circle(msp, layer):
    return msp.add_circle((0, 0), 50, dxfattribs={"layer": layer})


def _by_code(p, code):
    return [i for i in p.issues if i.code == code]


def test_unmapped_layers_reported_with_counts_and_refs(tmp_path: Path):
    path, h = _plan(
        tmp_path,
        extra=[("NOTES", _line), ("NOTES", _circle), ("NOTES", _line), ("DIMS", _line)],
    )
    issues = _by_code(read_dxf(path, 3000, ceiling_height=3000), "unmapped_layer")
    assert [i.severity for i in issues] == ["warning"] * 2
    notes, dims = issues
    assert "NOTES" in notes.message and "1 CIRCLE, 2 LINE" in notes.message
    assert [s.entity_handle for s in notes.sources] == h["NOTES"]
    assert [s.entity_handle for s in dims.sources] == h["DIMS"]


def test_unmapped_layer_refs_capped_with_total(tmp_path: Path):
    path, h = _plan(tmp_path, extra=[("NOTES", _line)] * 25)
    (issue,) = _by_code(read_dxf(path, 3000, ceiling_height=3000), "unmapped_layer")
    assert "25 LINE" in issue.message and "first 20 of 25" in issue.message
    assert [s.entity_handle for s in issue.sources] == h["NOTES"][:20]


@pytest.mark.parametrize(
    "ring",
    [
        [(0, 0), (1000, 1000), (1000, 0), (0, 1000)],  # bow-tie
        [(0, 0), (500, 0), (1000, 0)],  # collinear, zero area
    ],
)
def test_invalid_floor_is_blocking_and_excluded(tmp_path: Path, ring):
    path, h = _plan(tmp_path, floor=ring)
    p = read_dxf(path, 3000, ceiling_height=3000)
    (issue,) = _by_code(p, "invalid_floor_boundary")
    assert issue.severity == "blocking"
    assert [s.entity_handle for s in issue.sources] == [h["floor"]]
    assert p.buildings[0].floors[0].boundaries == []


def test_clockwise_floor_is_valid(tmp_path: Path):
    ring = [(0, 0), (0, 1000), (1000, 1000), (1000, 0)]
    p = read_dxf(_plan(tmp_path, floor=ring)[0], 3000, ceiling_height=3000)
    assert [i.code for i in p.issues] == ["elevation_defaulted", "wall_role_inferred", "room_outline_open", "no_closed_rooms", "roof_type_unknown"]
    assert [b.polygon for b in p.buildings[0].floors[0].boundaries] == [ring]


def test_build_blocked_on_bow_tie_floor(tmp_path: Path):
    path, _ = _plan(tmp_path, floor=[(0, 0), (1000, 1000), (1000, 0), (0, 1000)])
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["build", str(path), "--wall-height", "3000", "--ceiling-height", "3000", "--out", str(out)])
    assert exc.value.code == 1
    assert {p.name for p in out.iterdir()} == {"t.canonical.json", "t.report.md"}


def test_no_walls_carries_unpaired_refs(tmp_path: Path):
    path = _dxf(tmp_path, 4, [((0, 0), (1000, 0))])
    (issue,) = _by_code(read_dxf(path, 3000, ceiling_height=3000), "no_walls")
    handle = ezdxf.readfile(path).modelspace()[0].dxf.handle
    assert [s.entity_handle for s in issue.sources] == [handle]


def test_bad_height_rejected():
    with pytest.raises(ValueError):
        read_dxf(FIXTURE_A, wall_height=0, ceiling_height=0)


def _eq_walls(p):
    (w,) = p.buildings[0].floors[0].walls
    return w


def test_units_flag_scales_unitless_like_mm(tmp_path: Path):
    ref = read_dxf(
        _dxf(tmp_path, 4, [((0, 0), (1000, 0)), ((0, 200), (1000, 200))]), 3000
    )
    got = read_dxf(
        _dxf(tmp_path, 0, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))]),
        3000,
        user_units="m",
    )
    a, b = _eq_walls(ref), _eq_walls(got)
    assert b.centreline.start == pytest.approx(a.centreline.start, abs=1e-9)
    assert b.centreline.end == pytest.approx(a.centreline.end, abs=1e-9)
    assert b.thickness.value == pytest.approx(a.thickness.value, abs=1e-9)
    assert b.thickness.source == "user_provided"
    assert "units_user_provided" in [i.code for i in got.issues]


def test_units_conflict_blocks(tmp_path: Path):
    p = read_dxf(_dxf(tmp_path, 4, [((0, 0), (1, 0))]), 3000, ceiling_height=3000, user_units="m")
    assert [i.code for i in p.issues] == ["units_conflict"] and p.buildings == []
    assert "4" in p.issues[0].message and "m" in p.issues[0].message


def test_units_matching_header_accepted(tmp_path: Path):
    p = read_dxf(
        _dxf(tmp_path, 6, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))]),
        3000,
        user_units="m",
    )
    assert not [i for i in p.issues if i.code.startswith("units_")]
    assert _eq_walls(p).thickness.source == "source_extracted"


def test_units_cli_exit_codes(tmp_path: Path, capsys):
    unitless = _dxf(tmp_path, 0, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))])
    out = tmp_path / "o.json"
    base = ["interpret", str(unitless), "--wall-height", "3000", "--ceiling-height", "3000", "--out", str(out)]

    def code(args):
        with pytest.raises(SystemExit) as e:
            main(args)
        return e.value.code

    assert code(base) == 1  # units_missing
    with pytest.raises(SystemExit) as e:
        main(base + ["--units", "~"])
    assert e.value.code == 2
    main(base + ["--units", "m"])  # no SystemExit: ok
    assert (
        code(
            base[:1]
            + [str(_dxf(tmp_path, 4, [((0, 0), (1, 0))]))]
            + ["--units", "m", "--wall-height", "3000", "--ceiling-height", "3000", "--out", str(out)]
        )
        == 1
    )


# --- B2: unsupported / malformed $INSUNITS ---------------------------------
def _hdr(tmp_path: Path, raw: str) -> Path:
    """Valid DXF whose $INSUNITS value is overwritten as raw text."""
    path = _dxf(tmp_path, 4, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))])
    new = "$INSUNITS\n 70\n" + raw
    text = re.sub(r"\$INSUNITS\s+70\s+\S+", lambda _: new, path.read_text())
    assert new in text
    path.write_text(text)
    return path


@pytest.mark.parametrize("code", [21, 22, 99, -1, 10**6])
def test_unsupported_insunits_blocks_cleanly(tmp_path: Path, code):
    p = read_dxf(_dxf(tmp_path, code, [((0, 0), (1, 0))]), 3000, ceiling_height=3000)
    assert [i.code for i in p.issues] == ["units_unsupported"] and p.buildings == []
    assert p.issues[0].severity == "blocking" and str(code) in p.issues[0].message


def test_unsupported_insunits_with_units_flag_is_conflict(tmp_path: Path):
    p = read_dxf(_dxf(tmp_path, 21, [((0, 0), (1, 0))]), 3000, ceiling_height=3000, user_units="m")
    assert [i.code for i in p.issues] == ["units_conflict"]


@pytest.mark.parametrize("raw", ["abc", "", "9" * 40])
def test_malformed_insunits_never_tracebacks(tmp_path: Path, raw):
    path = _hdr(tmp_path, raw)
    try:
        p = read_dxf(path, 3000, ceiling_height=3000)
    except InputError:
        return  # rejected at load: clean exit 3
    assert [i.code for i in p.issues] == ["units_unsupported"]


def test_unsupported_insunits_cli_exit_1(tmp_path: Path, capsys):
    path = _dxf(tmp_path, 21, [((0, 0), (1, 0))])
    for cmd in ("interpret", "build"):
        out = tmp_path / "o" if cmd == "build" else tmp_path / "o.json"
        with pytest.raises(SystemExit) as e:
            main([cmd, str(path), "--wall-height", "3000", "--ceiling-height", "3000", "--out", str(out)])
        assert e.value.code == 1
    assert "units_unsupported" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        main(["interpret", str(_hdr(tmp_path, "abc")), "--wall-height", "3000", "--ceiling-height", "3000"])
    assert e.value.code in (1, 3)


# --- B1: OCS / extrusion ----------------------------------------------------
def _ocs_dxf(tmp_path: Path, name, wall_pts, floor_pts, extrusion=(0, 0, 1)) -> Path:
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    attrs = {"extrusion": extrusion}
    for a, b in [((0, 0), (4000, 0)), ((0, 200), (4000, 200))]:  # wall (lines = WCS)
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    if wall_pts:
        msp.add_lwpolyline(wall_pts, dxfattribs={"layer": "A-WALL", **attrs})
    if floor_pts:
        msp.add_lwpolyline(
            floor_pts, close=True, dxfattribs={"layer": "A-FLOR", **attrs}
        )
    path = tmp_path / f"{name}.dxf"
    doc.saveas(path)
    return path


def _geom(p):
    f = p.buildings[0].floors[0]
    return (
        sorted(
            (w.centreline.start, w.centreline.end, w.thickness.value) for w in f.walls
        ),
        [b.polygon for b in f.boundaries],
    )


def test_flipped_extrusion_matches_mirrored_points(tmp_path: Path):
    floor_wcs = [(0, 0), (-4000, 0), (-4000, 3000), (0, 3000)]  # x < 0 in WCS
    ref = read_dxf(_ocs_dxf(tmp_path, "ref", None, floor_wcs), 3000, ceiling_height=3000)
    # OCS with extrusion (0,0,-1): world x = -ocs x, so author mirrored x
    floor_ocs = [(-x, y) for x, y in floor_wcs]
    got = read_dxf(_ocs_dxf(tmp_path, "got", None, floor_ocs, (0, 0, -1)), 3000, ceiling_height=3000)
    assert _geom(got)[1] == _geom(ref)[1] == [floor_wcs]


def test_flipped_extrusion_wall_polyline(tmp_path: Path):
    # closed rectangle outline on A-WALL: two 200 mm faces; x spans 5000..9000 in WCS
    wcs = [(5000, 1000), (9000, 1000), (9000, 1200), (5000, 1200)]

    def build(name, pts, ext):
        doc = ezdxf.new("R2018", setup=False)
        doc.header["$INSUNITS"] = 4
        doc.modelspace().add_lwpolyline(
            pts, close=True, dxfattribs={"layer": "A-WALL", "extrusion": ext}
        )
        path = tmp_path / f"{name}.dxf"
        doc.saveas(path)
        return read_dxf(path, 3000, ceiling_height=3000)

    ref = build("wref", wcs, (0, 0, 1))
    got = build("wgot", [(-x, y) for x, y in wcs], (0, 0, -1))
    assert _geom(got) == _geom(ref)
    assert _geom(ref)[0][0][0][0] == pytest.approx(5000)


def test_default_extrusion_unchanged_and_elevation_ignored(tmp_path: Path):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in [((0, 0), (4000, 0)), ((0, 200), (4000, 200))]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline(
        [(0, 0), (1000, 0), (1000, 1000)],
        close=True,
        dxfattribs={"layer": "A-FLOR", "elevation": 500},
    )
    path = tmp_path / "e.dxf"
    doc.saveas(path)
    p = read_dxf(path, 3000, ceiling_height=3000)
    assert _geom(p)[1] == [[(0, 0), (1000, 0), (1000, 1000)]]


def test_non_z_extrusion_flagged_and_skipped(tmp_path: Path):
    ring = [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]
    path = _ocs_dxf(tmp_path, "x", None, ring, (1, 0, 0))
    p = read_dxf(path, 3000, ceiling_height=3000)
    (i,) = [i for i in p.issues if i.code == "unsupported_extrusion"]
    assert i.severity == "warning" and i.sources[0].layer == "A-FLOR"
    assert i.sources[0].entity_handle and _geom(p)[1] == []


# --- ceiling (schema 0.5.0) -------------------------------------------------


def _codes(p, code):
    return [i for i in p.issues if i.code == code]


def test_ceiling_built_from_each_boundary_with_derived_elevation():
    f = read_dxf(FIXTURE_A, 3000, ceiling_height=2600).buildings[0].floors[0]
    assert f.ceiling_height.value == 2600 and f.ceiling_height.source == "user_provided"
    assert f.boundaries and len(f.ceilings) == len(f.boundaries)
    for b, c in zip(f.boundaries, f.ceilings, strict=True):
        assert c.polygon == b.polygon and c.sources == b.sources
        assert c.elevation.value == f.elevation.value + 2600
        assert c.elevation.source == "inferred"  # derived sum, not user's number


def test_ceiling_height_missing_is_blocking_only_with_walls(tmp_path):
    p = read_dxf(FIXTURE_A, 3000)
    (i,) = _codes(p, "ceiling_height_missing")
    assert i.severity == "blocking" and p.buildings[0].floors[0].ceilings == []
    no_walls = read_dxf(_dxf(tmp_path, 4, []), 3000)
    assert not _codes(no_walls, "ceiling_height_missing")


def test_ceiling_without_boundary_warns_and_builds_nothing(tmp_path):
    path, _ = _plan(tmp_path)
    p = read_dxf(path, 3000, ceiling_height=2600)
    (i,) = _codes(p, "ceiling_not_built")
    assert i.severity == "warning" and p.buildings[0].floors[0].ceilings == []


def test_ceiling_above_walls_warns_but_equal_or_lower_does_not():
    assert _codes(read_dxf(FIXTURE_A, 3000, ceiling_height=3001), "ceiling_above_walls")
    for h in (3000, 2500):
        p = read_dxf(FIXTURE_A, 3000, ceiling_height=h)
        assert not _codes(p, "ceiling_above_walls")


def test_ceiling_height_must_be_positive():
    with pytest.raises(ValueError, match="ceiling height"):
        read_dxf(FIXTURE_A, 3000, ceiling_height=0)


def test_a_ceiling_higher_than_the_walls_raises_the_walls_to_it_and_says_so():
    # the preset's walls are 2700; a 9000 ceiling must not float above them (roof and stair poked through)
    p = read_dxf(FIXTURE_A, building_type="residential", ceiling_height=9000)
    f = p.buildings[0].floors[0]
    assert {(w.height.value, w.height.source) for w in f.walls} == {(9000.0, "inferred")}  # the assumed walls, raised to the ceiling
    (issue,) = _by_code(p, "ceiling_above_walls")
    assert "2700" in issue.message and "raised" in issue.message
    (note,) = _by_code(p, "wall_height_defaulted")  # reports the value actually used, not the preset's 2700
    assert "raised to 9000" in note.message
    assert f.ceilings[0].elevation.value == f.finished_level_mm + 9000  # the ceiling plane: finished floor (200 slab) + 9000
    assert f.roofs[0].base_elevation.value == f.ceilings[0].elevation.value  # the roof sits on the raised walls, above it
    # a wall height the user gave is a known measurement: kept, with a warning about the gap (never altered)
    q = read_dxf(FIXTURE_A, 3000, ceiling_height=3500)
    assert {(w.height.value, w.height.source) for w in q.buildings[0].floors[0].walls} == {(3000.0, "user_provided")}
    (gap,) = _by_code(q, "ceiling_above_walls")
    assert "kept" in gap.message and "gap above the walls" in gap.message
    # ...also when the ceiling is only the preset's assumed one
    t = read_dxf(FIXTURE_A, 2000, building_type="residential")  # preset ceiling 2700 above the user's 2000 walls
    assert {(w.height.value, w.height.source) for w in t.buildings[0].floors[0].walls} == {(2000.0, "user_provided")}
    assert "ceiling_above_walls" in [i.code for i in t.issues]
    # an equal or lower ceiling leaves the walls alone
    r = read_dxf(FIXTURE_A, 3000, ceiling_height=2500)
    assert {(w.height.value, w.height.source) for w in r.buildings[0].floors[0].walls} == {(3000.0, "user_provided")}


def _metre_house(tmp_path: Path, insunits: int):
    walls = [((0, 0), (8, 0)), ((0, 0.15), (8, 0.15)), ((0, 4), (8, 4)), ((0, 4.15), (8, 4.15))]
    return _dxf(tmp_path, insunits, walls)


def test_implausible_size_for_the_header_units_is_warned_not_changed(tmp_path: Path):
    # a drawing made in metres but flagged as inches: 8 "inches" is a 203 mm building
    p = read_dxf(_metre_house(tmp_path, 1), 3000, ceiling_height=3000)
    (i,) = [i for i in p.issues if i.code == "units_implausible"]
    assert i.severity == "warning" and "203.2 mm" in i.message and "INSUNITS=1" in i.message
    assert p.buildings and not p.buildings[0].floors[0].walls  # read as drawn, not rescaled
    ok = read_dxf(_metre_house(tmp_path, 6), 3000, ceiling_height=3000)
    assert "units_implausible" not in [i.code for i in ok.issues]


def test_units_override_replaces_a_wrong_header_and_says_so(tmp_path: Path):
    path = _metre_house(tmp_path, 1)
    assert [i.code for i in read_dxf(path, 3000, ceiling_height=3000, user_units="m").issues] == ["units_conflict"]
    p = read_dxf(path, 3000, ceiling_height=3000, user_units="m", units_override=True)
    codes = [i.code for i in p.issues]
    assert "units_overridden" in codes and "units_implausible" not in codes and "units_conflict" not in codes
    walls = p.buildings[0].floors[0].walls
    assert sorted(w.thickness.value for w in walls) == [150, 150]
    assert {w.thickness.source for w in walls} == {"user_provided"}
    assert sorted(w.centreline.end[0] for w in walls) == [8000, 8000]


def test_drawing_without_plan_layers_says_so(tmp_path: Path):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 0
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True, dxfattribs={"layer": "0"})
    path = tmp_path / "sheet.dxf"
    doc.saveas(path)
    p = read_dxf(path, 3000, ceiling_height=3000)  # no units either
    assert [(i.code, i.severity) for i in p.issues] == [("no_plan_geometry", "blocking"), ("units_missing", "blocking")]
    p = read_dxf(path, 3000, ceiling_height=3000, user_units="m")
    assert "no_plan_geometry" in [i.code for i in p.issues] and "no_walls" in [i.code for i in p.issues]
