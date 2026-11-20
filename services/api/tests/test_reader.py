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
    assert p.issues == []
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
        ("wall_height_missing", "blocking")
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


def test_bad_height_rejected():
    with pytest.raises(ValueError):
        read_dxf(FIXTURE_A, wall_height=0)
