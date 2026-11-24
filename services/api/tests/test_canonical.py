import json

import pytest
from pydantic import ValidationError

from api.engine.canonical.model import (
    Building,
    Floor,
    FloorBoundary,
    Issue,
    LineGeometry,
    Measured,
    Opening,
    Project,
    SourceRef,
    Wall,
)


def _m(value, source="defaulted"):
    return Measured(value=value, source=source)


def _opening(**kw) -> dict:
    # ADR-002 worked example door: wall-001 runs (0,100)-(8200,100)
    d = {
        "id": "opening-001",
        "kind": "door",
        "wall_id": "wall-001",
        "span": LineGeometry(start=(1000, 100), end=(1900, 100)),
        "offset": _m(1000, "source_extracted"),
        "width": _m(900, "source_extracted"),
        "height": _m(2100),
        "sill_height": _m(0),
        "sources": [SourceRef(layer="A-DOOR", entity_handle="D1")],
    }
    return {**d, **kw}


def _project() -> Project:
    a = SourceRef(layer="A-WALL", entity_handle="31")
    b = SourceRef(layer="A-WALL", entity_handle="32")
    wall = Wall(
        id="wall-001",
        centreline=LineGeometry(start=(0, 100), end=(8200, 100)),
        thickness=Measured(value=200, source="source_extracted"),
        height=Measured(value=3000, source="user_provided"),
        sources=[a, b],
    )
    floor = Floor(
        id="floor-0",
        name="Ground",
        elevation=Measured(value=0, source="defaulted"),
        walls=[wall],
        openings=[_opening()],
        boundaries=[
            FloorBoundary(
                id="fb-001",
                polygon=[(0, 0), (4000, 0), (4000, 5200), (0, 5200)],
                sources=[SourceRef(layer="A-FLOR", entity_handle="3D")],
            )
        ],
    )
    return Project(
        id="fixture_a",
        source_file="fixture_a.dxf",
        buildings=[Building(id="bldg-0", floors=[floor])],
        issues=[
            Issue(code="unpaired_segment", severity="warning", message="x", sources=[a])
        ],
    )


def test_json_round_trip_is_lossless():
    p = _project()
    assert Project.model_validate_json(p.model_dump_json()) == p


def test_json_shape_keeps_units_provenance_and_handles():
    d = json.loads(_project().model_dump_json())
    wall = d["buildings"][0]["floors"][0]["walls"][0]
    assert d["schema_version"] == "0.10.0" and d["units"] == "mm"
    assert wall["thickness"] == {
        "value": 200.0,
        "unit": "mm",
        "source": "source_extracted",
    }
    assert wall["height"]["source"] == "user_provided"
    assert [s["entity_handle"] for s in wall["sources"]] == ["31", "32"]
    assert wall["centreline"] == {
        "kind": "line",
        "start": [0.0, 100.0],
        "end": [8200.0, 100.0],
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"value": 1, "source": "guessed"},  # unknown provenance
        {"value": 1, "unit": "m", "source": "defaulted"},  # non-canonical unit
        {"value": 1, "source": "defaulted", "note": "x"},  # unknown key
        {"value": 1},  # provenance required
    ],
)
def test_measured_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        Measured.model_validate(bad)


def test_issue_severity_restricted():
    with pytest.raises(ValidationError):
        Issue(code="c", severity="info", message="m")


def test_opening_json_shape():
    d = json.loads(_project().model_dump_json())
    (o,) = d["buildings"][0]["floors"][0]["openings"]
    assert o["type"] == "opening" and o["kind"] == "door"
    assert o["wall_id"] == "wall-001"
    assert o["span"] == {
        "kind": "line",
        "start": [1000.0, 100.0],
        "end": [1900.0, 100.0],
    }
    assert o["width"] == {"value": 900.0, "unit": "mm", "source": "source_extracted"}
    assert o["sill_height"]["source"] == "defaulted"
    assert o["sources"] == [{"format": "dxf", "layer": "A-DOOR", "entity_handle": "D1"}]


def test_floor_without_openings_serialises_empty_list():
    f = Floor(id="f", name="L0", elevation=_m(0))
    assert json.loads(f.model_dump_json())["openings"] == []


@pytest.mark.parametrize(
    "bad",
    [
        {"width": _m(0, "source_extracted")},
        {"height": _m(0)},
        {"height": _m(-1)},
        {"sill_height": _m(-1)},
        {"offset": _m(-1)},
        {"width": _m(900.01, "source_extracted")},  # != |span|
        {"span": LineGeometry(start=(1000, 100), end=(1900, 101))},  # skewed
        {"span": LineGeometry(start=(1000, 100), end=(1000, 100))},  # degenerate
        {"span": LineGeometry(start=(1900, 100), end=(1000, 100))},  # reversed
        {"sources": []},
        {"kind": "arch"},
    ],
)
def test_opening_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        Opening(**_opening(**bad))


def test_opening_width_within_tolerance_is_accepted():
    Opening(**_opening(width=_m(900 + 1e-7, "source_extracted")))


def _floor(*openings, height=3000) -> Floor:
    wall = Wall(
        id="wall-001",
        centreline=LineGeometry(start=(0, 100), end=(5000, 100)),
        thickness=_m(200, "source_extracted"),
        height=None if height is None else _m(height, "user_provided"),
        sources=[SourceRef(layer="A-WALL", entity_handle="1")],
    )
    return Floor(
        id="floor-0",
        name="L0",
        elevation=_m(0),
        walls=[wall],
        openings=[Opening(**o) for o in openings],
    )


def _window(**kw):
    # ADR-002 worked example window, 3000..3600
    return _opening(
        **{
            "id": "opening-002",
            "kind": "window",
            "span": LineGeometry(start=(3000, 100), end=(3600, 100)),
            "offset": _m(3000, "source_extracted"),
            "width": _m(600, "source_extracted"),
            "height": _m(1200),
            "sill_height": _m(900),
            **kw,
        }
    )


def test_floor_accepts_valid_openings():
    f = _floor(_opening(), _window())
    assert [o.id for o in f.openings] == ["opening-001", "opening-002"]
    _floor(_window(sill_height=_m(1800)))  # sill + height == wall height: allowed
    _floor(_window(sill_height=_m(5000)), height=None)  # unknown height: no check


def _vertical_span(**kw):
    return _opening(span=LineGeometry(start=(100, 0), end=(100, 900)), **kw)


@pytest.mark.parametrize(
    "openings, match",
    [
        ((_opening(wall_id="wall-999"),), "not on floor-0"),
        ((_vertical_span(offset=_m(0)),), "not within"),  # wrong axis
        (
            (_opening(span=LineGeometry(start=(1000, 0), end=(1900, 0))),),
            "not within",  # parallel, off the centreline (on a face)
        ),
        (
            (
                _opening(
                    span=LineGeometry(start=(4500, 100), end=(5400, 100)),
                    offset=_m(4500),
                ),
            ),
            "not within",  # past the wall end
        ),
        ((_opening(offset=_m(999)),), "offset"),
        ((_window(sill_height=_m(1801)),), "exceeds"),  # 1801 + 1200 > 3000
        ((_opening(), _opening(id="opening-001", wall_id="wall-001")), "duplicate"),
        (
            (
                _opening(),
                _window(
                    span=LineGeometry(start=(1800, 100), end=(2400, 100)),
                    offset=_m(1800),
                ),
            ),
            "overlap",
        ),
    ],
)
def test_floor_rejects_invalid_openings(openings, match):
    with pytest.raises(ValidationError, match=match):
        _floor(*openings)


def test_touching_openings_do_not_overlap():
    _floor(
        _opening(),
        _window(span=LineGeometry(start=(1900, 100), end=(2500, 100)), offset=_m(1900)),
    )
