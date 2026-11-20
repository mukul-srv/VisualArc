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
    Project,
    SourceRef,
    Wall,
)


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
    assert d["schema_version"] == "0.2.0" and d["units"] == "mm"
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
