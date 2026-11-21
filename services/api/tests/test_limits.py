"""T21a: provisional complexity limits are enforced before interpretation, with clear
errors (CLI exit 3, API 422) and exactly at the documented boundary."""

import dataclasses
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api.cli import main
from api.engine.adapters.dxf.reader import InputError, check_complexity, read_dxf
from api.engine.settings import DEFAULTS
from api.main import app

ROOT = Path(__file__).resolve().parents[3]
INPUT = ROOT / "fixtures" / "input"


def _doc(walls=0, markers=0, extra=0, polyline_edges=0):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for i in range(walls):
        msp.add_line((0, i), (10, i), dxfattribs={"layer": "A-WALL"})
    if polyline_edges:  # open polyline with N edges = N+1 vertices
        pts = [(k, 0) for k in range(polyline_edges + 1)]
        msp.add_lwpolyline(pts, dxfattribs={"layer": "a-wall"})
    for i in range(markers):
        msp.add_lwpolyline(
            [(0, 0), (1, 0), (1, 1), (0, 1)],
            close=True,
            dxfattribs={"layer": "A-DOOR" if i % 2 else "A-GLAZ"},
        )
    for i in range(extra):
        msp.add_text(f"t{i}", dxfattribs={"layer": "NOTES"})
    return doc


def _save(tmp_path, doc, name="t.dxf"):
    p = tmp_path / name
    doc.saveas(p)
    return p


def test_enforced_defaults_are_the_approved_values():
    assert DEFAULTS.max_wall_segments == 600
    assert DEFAULTS.max_opening_markers == 120
    assert DEFAULTS.max_entities == 5000
    assert DEFAULTS.max_dxf_bytes == 5 * 2**20


@pytest.mark.parametrize(
    "kwargs, field, limit",
    [
        ({"walls": 5}, "max_wall_segments", 5),
        ({"markers": 5}, "max_opening_markers", 5),
        ({"extra": 5}, "max_entities", 5),
    ],
)
def test_boundary_at_limit_passes_one_over_rejected(kwargs, field, limit):
    s = dataclasses.replace(
        DEFAULTS, max_wall_segments=10**6, max_opening_markers=10**6, max_entities=10**6
    )
    s = dataclasses.replace(s, **{field: limit})
    check_complexity(_doc(**kwargs), s)  # exactly at the limit: accepted
    over = {k: v + 1 for k, v in kwargs.items()}
    with pytest.raises(InputError) as e:
        check_complexity(_doc(**over), s)
    msg = str(e.value)
    assert str(limit) in msg and str(limit + 1) in msg and "provisional" in msg


def test_polyline_edges_count_as_wall_segments_case_insensitively():
    s = dataclasses.replace(DEFAULTS, max_wall_segments=7)
    check_complexity(_doc(polyline_edges=7), s)  # layer "a-wall", 7 edges
    with pytest.raises(InputError, match="8 wall segments"):
        check_complexity(_doc(polyline_edges=8), s)


def test_closed_polyline_counts_all_edges():
    doc = ezdxf.new("R2018", setup=False)
    doc.modelspace().add_lwpolyline(
        [(0, 0), (1, 0), (1, 1), (0, 1)], close=True, dxfattribs={"layer": "A-WALL"}
    )
    check_complexity(doc, dataclasses.replace(DEFAULTS, max_wall_segments=4))
    with pytest.raises(InputError, match="4 wall segments"):
        check_complexity(doc, dataclasses.replace(DEFAULTS, max_wall_segments=3))


def test_annotation_does_not_consume_the_wall_or_marker_caps():
    check_complexity(
        _doc(extra=4000), DEFAULTS
    )  # text on other layers: under 5000 total


def test_default_limits_reject_601_wall_lines_fast_via_read_dxf(tmp_path):
    p = _save(tmp_path, _doc(walls=601))
    with pytest.raises(InputError, match="601 wall segments.*limit is 600"):
        read_dxf(p, 3000, ceiling_height=3000)


def test_cli_exits_3_with_clear_message(tmp_path, capsys):
    p = _save(tmp_path, _doc(walls=601))
    with pytest.raises(SystemExit) as e:
        main(
            ["interpret", str(p), "--wall-height", "3000", "--ceiling-height", "3000", "--out", str(tmp_path / "o")]
        )
    assert e.value.code == 3
    err = capsys.readouterr().err
    assert "601 wall segments" in err and "limit is 600" in err


def test_api_upload_rejected_422_and_cleaned_up(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path / "data"))
    p = _save(tmp_path, _doc(markers=121))
    r = TestClient(app).post("/api/v1/uploads", content=p.read_bytes())
    assert r.status_code == 422
    assert (
        "121 opening markers" in r.json()["detail"]
        and "limit is 120" in r.json()["detail"]
    )
    assert list((tmp_path / "data").glob("*.dxf")) == []


def test_committed_fixtures_are_within_the_limits():
    for f in INPUT.glob("*.dxf"):
        check_complexity(ezdxf.readfile(f))  # includes fixture_d (9 tiles)
