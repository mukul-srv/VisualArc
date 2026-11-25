"""Lighting setting (Phase 1/19): roles, validation, versions, snapshot/restore, floor removal."""

import pytest
from fastapi.testclient import TestClient
from test_building import P, _b, _floor

from api.main import app


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))


def _light(floor, **kw):
    return {"id": "l1", "kind": "point", "floor_id": floor, "x_mm": 1000, "y_mm": 2000,
            "height_mm": 2400, "color": "#ffeedd", "intensity": 3, **kw}


def test_default_set_validate_version_restore_and_floor_removal():
    c = TestClient(app)
    pid = c.post(P, json={"name": "L"}).json()["project_id"]
    g = _floor(c, pid, "Ground", 0)
    f = _floor(c, pid, "First", 3200)
    assert _b(c, pid)["lighting"] == {"location": None, "north_deg": 0.0, "lights": []}
    n = len(c.get(f"{P}/{pid}/versions").json())
    body = {"location": {"latitude": 51.5, "longitude": -0.12}, "north_deg": 30,
            "lights": [_light(g["id"]), _light(f["id"], id="l2", kind="spot")]}
    r = c.put(f"{P}/{pid}/lighting", json=body)
    assert r.status_code == 200, r.text
    assert len(c.get(f"{P}/{pid}/versions").json()) == n + 1
    assert _b(c, pid)["lighting"]["location"]["latitude"] == 51.5
    assert c.get(f"{P}/{pid}").json()["lighting"]["north_deg"] == 30
    v_set = c.get(f"{P}/{pid}").json()["version"]
    bad = [{"location": {"latitude": 91, "longitude": 0}}, {"north_deg": 360},
           {"lights": [_light(g["id"], color="red")]}, {"lights": [_light(g["id"], kind="laser")]},
           {"lights": [_light(g["id"], intensity=-1)]}, {"lights": [_light("nope")]},
           {"lights": [_light(g["id"]), _light(g["id"])]}, {"extra": 1}]
    for b in bad:
        assert c.put(f"{P}/{pid}/lighting", json=b).status_code == 422, b
    assert _b(c, pid)["lighting"]["north_deg"] == 30  # nothing stored by the rejected calls
    c.put(f"{P}/{pid}/lighting", json={})  # clear
    assert _b(c, pid)["lighting"]["lights"] == []
    assert c.get(f"{P}/{pid}?version={v_set}").json()["lighting"]["lights"][0]["id"] == "l1"
    assert c.post(f"{P}/{pid}/versions/{v_set}/restore").status_code == 201
    assert len(_b(c, pid)["lighting"]["lights"]) == 2
    c.delete(f"{P}/{pid}/floors/{f['id']}")  # its light goes with it
    assert [x["id"] for x in _b(c, pid)["lighting"]["lights"]] == ["l1"]


def test_lighting_roles():
    owner, editor, viewer, stranger = (TestClient(app) for _ in range(4))
    pid = owner.post(P, json={"name": "L"}).json()["project_id"]
    g = _floor(owner, pid, "Ground", 0)
    for c, role in ((editor, "editor"), (viewer, "viewer")):
        email = c.get("/api/v1/auth/me").json()["email"]
        owner.put(f"{P}/{pid}/access", json={"email": email, "role": role})
    body = {"north_deg": 10, "lights": [_light(g["id"])]}
    url = f"{P}/{pid}/lighting"
    assert viewer.put(url, json=body).status_code == 404
    assert stranger.put(url, json=body).status_code == 404
    assert editor.put(url, json=body).status_code == 200
    assert viewer.get(f"{P}/{pid}/building").json()["lighting"]["north_deg"] == 10  # viewers see it
