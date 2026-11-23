"""Projects made from the same file never share state: each owns its generation and artifacts."""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def _upload(c):
    return c.post("/api/v1/uploads", params={"filename": "plan.dxf"}, content=(INPUT / "fixture_a.dxf").read_bytes()).json()["upload_id"]


def _via_create(c, upload, name):
    pid = c.post(P, json={"name": name}).json()["project_id"]
    r = c.post(f"/api/v1/jobs/projects/{pid}/floors", json={"upload_id": upload, "floor_name": "G", "elevation": 0})
    jobs.execute(r.json()["job_id"])
    return pid


def _via_convert(c, upload, name):
    gid = c.post("/api/v1/generations", json={"upload_id": upload}).json()["generation_id"]
    return c.post(f"{P}/from-generation", json={"generation_id": gid, "name": name}).json()["project_id"]


def _change(c, pid, **body):
    r = c.post(f"/api/v1/jobs/projects/{pid}/parameters", json=body)
    jobs.execute(r.json()["job_id"])
    assert c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()["status"] == "succeeded"


def _state(c, pid):
    """Everything a project shows: its parameters, floors and a digest of every artifact."""
    m = c.get(f"{P}/{pid}").json()
    digest = {}
    for f in m["floors"]:
        for art in ("canonical", "glb", "meta"):
            digest[(f["id"], art)] = hashlib.sha256(
                c.get(f"/api/v1/generations/{f['generation_id']}/artifacts/{art}").content).hexdigest()
    return {"parameters": c.get(f"{P}/{pid}/parameters").json(), "floors": m["floors"], "version": m["version"], "digest": digest}


@pytest.mark.parametrize("make", [_via_create, _via_convert])
def test_two_projects_from_one_upload_do_not_affect_each_other(client, make):
    upload = _upload(client)
    a, b = make(client, upload, "A"), make(client, upload, "B")
    ga = client.get(f"{P}/{a}").json()["floors"][0]["generation_id"]
    gb = client.get(f"{P}/{b}").json()["floors"][0]["generation_id"]
    assert ga != gb  # each project owns its generation (and so its artifact files)
    before_b = _state(client, b)
    _change(client, a, wall_height=3300, roof_type="hip", slab_thickness=300)
    assert _state(client, b) == before_b  # B: same parameters, floors, version and artifact bytes
    # and the other way round, after A has been regenerated
    before_a = _state(client, a)
    _change(client, b, ceiling_height=2500)
    assert _state(client, a) == before_a
    assert client.get(f"{P}/{a}/parameters").json()["wall_height"]["value"] == 3300
    assert client.get(f"{P}/{b}/parameters").json()["wall_height"]["source"] == "defaulted"


def test_a_model_cannot_be_attached_to_two_projects(client):
    upload = _upload(client)
    gid = client.post("/api/v1/generations", json={"upload_id": upload}).json()["generation_id"]
    assert client.post(f"{P}/from-generation", json={"generation_id": gid, "name": "A"}).status_code == 201
    assert client.post(f"{P}/from-generation", json={"generation_id": gid, "name": "B"}).status_code == 409
    # even after the first project regenerated away from it (the old generation stays in its history)
    pid = client.get("/api/v1/projects").json()[0]["id"]
    _change(client, pid, wall_height=3000)
    assert client.post(f"{P}/from-generation", json={"generation_id": gid, "name": "C"}).status_code == 409
