import json
from pathlib import Path

import ezdxf
import pytest

from api.cli import main
from api.engine.adapters.dxf.reader import read_dxf

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
FIXTURE_A = FIXTURES / "input" / "fixture_a.dxf"


def test_fixture_a_known_dimensions():
    p = read_dxf(FIXTURE_A, wall_height=3000)
    assert [(i.code, i.severity) for i in p.issues] == [
        ("elevation_defaulted", "warning")
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
    main(["interpret", str(FIXTURE_A), "--wall-height", "3000", "--out", str(out)])
    expected = json.loads(
        (FIXTURES / "expected" / "fixture_a.canonical.json").read_text()
    )
    assert json.loads(out.read_text()) == expected


def test_missing_height_is_blocking_and_cli_fails(tmp_path: Path):
    p = read_dxf(FIXTURE_A)
    assert [(i.code, i.severity) for i in p.issues] == [
        ("wall_height_missing", "blocking"),
        ("elevation_defaulted", "warning"),
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
    p = read_dxf(_dxf(tmp_path, 0, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))]), 3000)
    assert [i.code for i in p.issues] == ["units_missing"] and p.buildings == []


def test_metre_dxf_converted_to_mm(tmp_path: Path):
    p = read_dxf(_dxf(tmp_path, 6, [((0, 0), (1, 0)), ((0, 0.2), (1, 0.2))]), 3000)
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
    issues = _by_code(read_dxf(path, 3000), "unmapped_layer")
    assert [i.severity for i in issues] == ["warning"] * 2
    notes, dims = issues
    assert "NOTES" in notes.message and "1 CIRCLE, 2 LINE" in notes.message
    assert [s.entity_handle for s in notes.sources] == h["NOTES"]
    assert [s.entity_handle for s in dims.sources] == h["DIMS"]


def test_unmapped_layer_refs_capped_with_total(tmp_path: Path):
    path, h = _plan(tmp_path, extra=[("NOTES", _line)] * 25)
    (issue,) = _by_code(read_dxf(path, 3000), "unmapped_layer")
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
    p = read_dxf(path, 3000)
    (issue,) = _by_code(p, "invalid_floor_boundary")
    assert issue.severity == "blocking"
    assert [s.entity_handle for s in issue.sources] == [h["floor"]]
    assert p.buildings[0].floors[0].boundaries == []


def test_clockwise_floor_is_valid(tmp_path: Path):
    ring = [(0, 0), (0, 1000), (1000, 1000), (1000, 0)]
    p = read_dxf(_plan(tmp_path, floor=ring)[0], 3000)
    assert [i.code for i in p.issues] == ["elevation_defaulted"]
    assert [b.polygon for b in p.buildings[0].floors[0].boundaries] == [ring]


def test_build_blocked_on_bow_tie_floor(tmp_path: Path):
    path, _ = _plan(tmp_path, floor=[(0, 0), (1000, 1000), (1000, 0), (0, 1000)])
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["build", str(path), "--wall-height", "3000", "--out", str(out)])
    assert exc.value.code == 1
    assert {p.name for p in out.iterdir()} == {"t.canonical.json"}


def test_no_walls_carries_unpaired_refs(tmp_path: Path):
    path = _dxf(tmp_path, 4, [((0, 0), (1000, 0))])
    (issue,) = _by_code(read_dxf(path, 3000), "no_walls")
    handle = ezdxf.readfile(path).modelspace()[0].dxf.handle
    assert [s.entity_handle for s in issue.sources] == [handle]


def test_bad_height_rejected():
    with pytest.raises(ValueError):
        read_dxf(FIXTURE_A, wall_height=0)


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
    p = read_dxf(_dxf(tmp_path, 4, [((0, 0), (1, 0))]), 3000, user_units="m")
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
    base = ["interpret", str(unitless), "--wall-height", "3000", "--out", str(out)]

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
            + ["--units", "m", "--wall-height", "3000", "--out", str(out)]
        )
        == 1
    )
