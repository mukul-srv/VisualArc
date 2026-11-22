"""Rename / remove a floor: versioned, editor+ only, ids stay unique, restore brings it back."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
H = {"wall_height": 3000, "ceiling_height": 3000}


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))


def _floor(c, pid, name, elev):
    up = c.post("/api/v1/uploads", content=(INPUT / "fixture_a.dxf").read_bytes()).json()["upload_id"]
    r = c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": name, "elevation": elev, **H})
    assert r.status_code == 201, r.text
    return r.json()["floor"]


@pytest.fixture
def proj():
    c = TestClient(app)
    pid = c.post(P, json={"name": "H"}).json()["project_id"]
    return c, pid, _floor(c, pid, "Ground", 0), _floor(c, pid, "First", 3000)


def _versions(c, pid):
    return c.get(f"{P}/{pid}/versions").json()


def test_rename_floor_is_a_new_version(proj):
    c, pid, g, _ = proj
    n = len(_versions(c, pid))
    r = c.patch(f"{P}/{pid}/floors/{g['id']}", json={"name": "  Basement "})
    assert r.status_code == 200 and r.json()["name"] == "Basement"
    names = [x["name"] for x in c.get(f"{P}/{pid}").json()["floors"]]
    assert names == ["Basement", "First"]
    vs = _versions(c, pid)
    assert len(vs) == n + 1 and vs[0]["message"] == "Renamed floor Ground to Basement"
    # the old version still shows the old name
    assert c.get(f"{P}/{pid}", params={"version": n}).json()["floors"][0]["name"] == "Ground"
    assert c.patch(f"{P}/{pid}/floors/{g['id']}", json={"name": "first"}).status_code == 422  # duplicate
    assert c.patch(f"{P}/{pid}/floors/{g['id']}", json={"name": " "}).status_code == 422
    assert c.patch(f"{P}/{pid}/floors/nope", json={"name": "X"}).status_code == 404


def test_remove_floor_versioned_ids_unique_and_restorable(proj):
    c, pid, g, f = proj
    n = len(_versions(c, pid))
    assert c.delete(f"{P}/{pid}/floors/{g['id']}").status_code == 204
    cur = c.get(f"{P}/{pid}").json()
    assert [x["id"] for x in cur["floors"]] == [f["id"]] and g["id"] not in cur["params"]
    assert _versions(c, pid)[0]["message"] == "Removed floor Ground"
    assert c.delete(f"{P}/{pid}/floors/{g['id']}").status_code == 404
    # a floor added now must not reuse an existing id
    new = _floor(c, pid, "Roof", 6000)
    assert new["id"] != f["id"]
    ids = [x["id"] for x in c.get(f"{P}/{pid}").json()["floors"]]
    assert len(ids) == len(set(ids)) == 2
    # restoring the version before the removal brings the floor back
    assert c.post(f"{P}/{pid}/versions/{n}/restore").status_code == 201
    assert [x["name"] for x in c.get(f"{P}/{pid}").json()["floors"]] == ["Ground", "First"]


def test_floor_edits_need_editor():
    owner, editor, viewer, stranger = (TestClient(app) for _ in range(4))
    pid = owner.post(P, json={"name": "H"}).json()["project_id"]
    g = _floor(owner, pid, "Ground", 0)
    for c, role in ((editor, "editor"), (viewer, "viewer")):
        email = c.get("/api/v1/auth/me").json()["email"]
        owner.put(f"{P}/{pid}/access", json={"email": email, "role": role})
    for c in (viewer, stranger):
        assert c.patch(f"{P}/{pid}/floors/{g['id']}", json={"name": "X"}).status_code == 404
        assert c.delete(f"{P}/{pid}/floors/{g['id']}").status_code == 404
    assert editor.patch(f"{P}/{pid}/floors/{g['id']}", json={"name": "X"}).status_code == 200
    assert editor.delete(f"{P}/{pid}/floors/{g['id']}").status_code == 204


def test_standalone_model_becomes_a_project():
    c = TestClient(app)
    up = c.post("/api/v1/uploads", content=(INPUT / "fixture_a.dxf").read_bytes()).json()["upload_id"]
    gid = c.post("/api/v1/generations", json={"upload_id": up, **H}).json()["generation_id"]
    r = c.post(f"{P}/from-generation", json={"generation_id": gid, "name": "Saved"})
    assert r.status_code == 201
    pid = r.json()["project_id"]
    m = c.get(f"{P}/{pid}").json()
    assert m["name"] == "Saved" and m["floors"][0]["generation_id"] == gid
    assert m["floors"][0]["elevation"]["source"] == "defaulted"
    assert c.get(f"/api/v1/generations/{gid}/artifacts/glb").status_code == 200
    # already in a project; someone else's model
    assert c.post(f"{P}/from-generation", json={"generation_id": gid, "name": "Again"}).status_code == 409
    other = TestClient(app)
    assert other.post(f"{P}/from-generation", json={"generation_id": gid, "name": "X"}).status_code == 404
