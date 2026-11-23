"""A standalone model that becomes a project floor can have its parameters changed (Phase 1 follow-up)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.db import GenerationRow, session
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def _standalone(c, **extra):
    up = c.post("/api/v1/uploads", params={"filename": "plan.dxf"}, content=(INPUT / "fixture_a.dxf").read_bytes()).json()["upload_id"]
    r = c.post("/api/v1/generations", json={"upload_id": up, **extra})
    assert r.status_code == 201, r.text
    return r.json()["generation_id"]


def _project_from(c, gid):
    return c.post(f"{P}/from-generation", json={"generation_id": gid, "name": "P"}).json()["project_id"]


def _change(c, pid, **body):
    r = c.post(f"/api/v1/jobs/projects/{pid}/parameters", json=body)
    if r.status_code != 202:
        return r
    jobs.execute(r.json()["job_id"])
    return c.get(f"/api/v1/jobs/{r.json()['job_id']}")


def _canon(c, pid):
    gid = c.get(f"{P}/{pid}").json()["floors"][0]["generation_id"]
    return c.get(f"/api/v1/generations/{gid}/artifacts/canonical").json()["buildings"][0]["floors"][0]


def test_a_converted_standalone_model_can_be_regenerated_by_its_owner(client):
    gid = _standalone(client, wall_height=3000, ceiling_height=2600)
    pid = _project_from(client, gid)
    got = client.get(f"{P}/{pid}/parameters").json()
    assert got["_legacy_floors"] == []  # the floor carries the request it was built from
    assert got["wall_height"] == {"value": 3000.0, "unit": "mm", "source": "user_provided"}  # kept from the upload
    job = _change(client, pid, slab_thickness=300)
    assert job.json()["status"] == "succeeded", job.json()
    f = _canon(client, pid)
    assert f["slabs"][0]["thickness"] == {"value": 300.0, "unit": "mm", "source": "user_provided"}
    assert f["ceiling_height"]["value"] == 2600.0  # what the model was built with is kept
    assert client.get(f"{P}/{pid}").json()["version"] == 2


def test_an_editor_can_change_parameters_of_a_converted_model(client):
    gid = _standalone(client)
    pid = _project_from(client, gid)
    editor = TestClient(app)
    email = editor.get("/api/v1/auth/me").json()["email"]
    assert client.put(f"{P}/{pid}/access", json={"email": email, "role": "editor"}).status_code in (200, 201)
    job = _change(editor, pid, roof_type="hip", roof_pitch=20)
    assert job.json()["status"] == "succeeded", job.json()
    roof = _canon(client, pid)["roofs"][0]
    assert roof["kind"] == "hip" and roof["pitch"]["source"] == "user_provided"


def test_a_floor_added_after_conversion_regenerates_too(client):
    pid = _project_from(client, _standalone(client))
    up = client.post("/api/v1/uploads", content=(INPUT / "fixture_a.dxf").read_bytes()).json()["upload_id"]
    r = client.post(f"/api/v1/jobs/projects/{pid}/floors", json={"upload_id": up, "floor_name": "Up", "elevation": 3000})
    jobs.execute(r.json()["job_id"])
    assert _change(client, pid, ceiling_height=2500).json()["status"] == "succeeded"
    assert client.get(f"{P}/{pid}/parameters").json()["_legacy_floors"] == []


def test_a_legacy_model_without_a_stored_request_gets_a_clear_message_with_the_way_out(client):
    gid = _standalone(client)
    with session() as db, db.begin():  # a model generated before requests were stored
        db.get(GenerationRow, gid).request = None
    pid = _project_from(client, gid)
    got = client.get(f"{P}/{pid}/parameters").json()
    assert got["_legacy_floors"] == ["Level 0"]
    r = _change(client, pid, ceiling_height=2500)
    assert r.status_code == 422
    assert "Level 0" in r.json()["detail"] and "Add floor" in r.json()["detail"]
    assert client.get(f"{P}/{pid}").json()["version"] == 1  # nothing changed


def test_defaults_of_a_converted_model_are_not_recorded_as_user_input(client):
    pid = _project_from(client, _standalone(client))  # nothing but the upload given
    params = client.get(f"{P}/{pid}").json()["params"]["floor-0"]
    assert params["building_type"]["source"] == "defaulted"
    assert params["wall_height"] == {"value": None, "source": "defaulted"}
    pid2 = _project_from(client, _standalone(client, building_type="commercial", wall_height=3100))
    params2 = client.get(f"{P}/{pid2}").json()["params"]["floor-0"]
    assert params2["building_type"] == {"value": "commercial", "source": "user_provided"}
    assert params2["wall_height"] == {"value": 3100.0, "source": "user_provided"}
