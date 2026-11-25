"""Per-element materials (Phase 1/18): project map, roles, validation, versions, survives regenerate."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_building import P, _b, _floor

from api import jobs
from api.building import MATERIAL_IDS
from api.main import app

INDEX = Path(__file__).resolve().parents[3] / "apps/web/public/materials/index.json"


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))


def test_library_index_matches_server_ids():
    index = json.loads(INDEX.read_text("utf-8"))
    assert {m["id"] for m in index} == MATERIAL_IDS
    for m in index:
        for f in ("color", "normal", "roughness"):
            assert (INDEX.parent / m["id"] / f"{f}.jpg").is_file()


def test_set_version_validate_and_survive_regenerate():
    c = TestClient(app)
    pid = c.post(P, json={"name": "M"}).json()["project_id"]
    g = _floor(c, pid, "Ground", 0)
    n = len(c.get(f"{P}/{pid}/versions").json())
    key = f"{g['id']}/wall-001"
    r = c.put(f"{P}/{pid}/materials", json={"materials": {key: "brick", f"{g['id']}/gone-9": "tile"}})
    assert r.status_code == 200, r.text
    assert len(c.get(f"{P}/{pid}/versions").json()) == n + 1
    assert _b(c, pid)["materials"][key] == "brick"
    assert c.get(f"{P}/{pid}").json()["materials"][key] == "brick"
    # unknown library id and bad key: rejected, nothing stored
    assert c.put(f"{P}/{pid}/materials", json={"materials": {key: "gold"}}).status_code == 422
    assert c.put(f"{P}/{pid}/materials", json={"materials": {"": "brick"}}).status_code == 422
    assert _b(c, pid)["materials"][key] == "brick"
    # regenerating the floor (parameters job) keeps the map; an element that vanished is tolerated
    r = c.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"wall_height": 2800})
    jobs.execute(r.json()["job_id"])
    assert c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()["stage"] == "done"
    assert _b(c, pid)["materials"][key] == "brick"
    # old versions keep their own map; removing the floor drops its keys
    v_set = n + 1
    assert c.put(f"{P}/{pid}/materials", json={"materials": {}}).status_code == 200
    assert c.get(f"{P}/{pid}?version={v_set}").json()["materials"][key] == "brick"
    c.put(f"{P}/{pid}/materials", json={"materials": {key: "stone"}})
    _floor(c, pid, "First", 3200)
    c.delete(f"{P}/{pid}/floors/{g['id']}")
    assert _b(c, pid)["materials"] == {}


def test_material_roles():
    owner, editor, viewer, stranger = (TestClient(app) for _ in range(4))
    pid = owner.post(P, json={"name": "M"}).json()["project_id"]
    _floor(owner, pid, "Ground", 0)
    for c, role in ((editor, "editor"), (viewer, "viewer")):
        email = c.get("/api/v1/auth/me").json()["email"]
        owner.put(f"{P}/{pid}/access", json={"email": email, "role": role})
    body = {"materials": {"f/w": "plaster"}}
    url = f"{P}/{pid}/materials"
    assert viewer.put(url, json=body).status_code == 404
    assert stranger.put(url, json=body).status_code == 404
    assert editor.put(url, json=body).status_code == 200
    assert viewer.get(f"{P}/{pid}/building").json()["materials"] == body["materials"]  # viewers see them
