"""A drawing whose header says inches but is drawn in metres, through the real upload -> layers -> split
path: the units override must survive every step (the form re-reads the file with the unit it chose)."""

from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api.main import app

HOUSE = Path(__file__).resolve().parents[3] / "fixtures" / "input" / "Two-story-house-410202.dxf"
U = "/api/v1/uploads"


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))


def _two_floors_in_metres(tmp_path: Path) -> bytes:
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 1  # inches: wrong, the walls are 0.15 "units" thick = a metre drawing
    for x0 in (0, 20):  # two 8 x 4 m floors 12 m apart
        for y, (a, b) in {0: (0, 8), 0.15: (0, 8), 4: (0, 8), 4.15: (0, 8)}.items():
            doc.modelspace().add_line((x0 + a, y), (x0 + b, y), dxfattribs={"layer": "A-WALL"})
        for x in (0, 7.85):
            doc.modelspace().add_line((x0 + x, 0), (x0 + x, 4.15), dxfattribs={"layer": "A-WALL"})
            doc.modelspace().add_line((x0 + x + 0.15, 0), (x0 + x + 0.15, 4.15), dxfattribs={"layer": "A-WALL"})
    path = tmp_path / "m.dxf"
    doc.saveas(path)
    return path.read_bytes()


def _split_body(cands, **extra):
    return {
        "project_name": "P", "wall_height": 2700, "ceiling_height": 2700, "building_type": "residential",
        "floors": [{"key": x["key"], "exclude": False, "name": x["key"], "offset_x": x["proposed_offset"]["x"],
                    "offset_y": x["proposed_offset"]["y"]} for x in cands], **extra,
    }


def _run(c: TestClient, data: bytes):
    up = c.post(U, content=data).json()
    uid = up["upload_id"]
    assert "units_implausible" in {i["code"] for i in up["issues"]}  # warned, nothing rescaled
    lay = c.post(f"{U}/{uid}/layers?units=m&units_override=true", json={}).json()
    # the floors are found under the chosen unit, and the override stays on record in the issues (the
    # form keys the flag on it, also while the split is still unconfirmed)
    assert len(lay["floor_candidates"]) == 2
    assert "units_overridden" in {i["code"] for i in lay["issues"]}
    return uid, lay["floor_candidates"]


def test_units_override_through_upload_layers_split(tmp_path):
    c = TestClient(app)
    uid, cands = _run(c, _two_floors_in_metres(tmp_path))
    refused = c.post(f"{U}/{uid}/split", json=_split_body(cands, units="m"))
    assert refused.status_code == 422 and "units" in refused.json()["detail"]  # a conflict is never silent
    ok = c.post(f"{U}/{uid}/split", json=_split_body(cands, units="m", units_override=True))
    assert ok.status_code == 201, ok.text
    assert len(ok.json()["floors"]) == 2


@pytest.mark.skipif(not HOUSE.is_file(), reason="house drawing not present")
def test_real_house_through_upload_layers_split():
    c = TestClient(app)
    uid, cands = _run(c, HOUSE.read_bytes())
    ok = c.post(f"{U}/{uid}/split", json=_split_body(cands, units="m", units_override=True))
    assert ok.status_code == 201, ok.text
