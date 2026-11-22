"""Standalone (recent) models: default name = uploaded file name, rename, soft delete."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _generate(c, filename="Villa plan.dxf"):
    up = c.post("/api/v1/uploads", params={"filename": filename},
                content=(INPUT / "fixture_a.dxf").read_bytes()).json()["upload_id"]
    r = c.post("/api/v1/generations", json={"upload_id": up, "wall_height": 3000, "ceiling_height": 3000})
    assert r.status_code == 201
    return r.json()["generation_id"]


def _recent(c):
    return {g["generation_id"]: g for g in c.get("/api/v1/generations/recent").json()}


def test_default_name_is_the_uploaded_file_name_and_paths_are_stripped(client):
    gid = _generate(client, r"C:\Users\me\Villa plan.dxf")
    assert _recent(client)[gid]["name"] == "Villa plan.dxf"
    unnamed = _generate(client, "")
    assert _recent(client)[unnamed]["name"] is None  # nothing sent: the UI falls back


def test_rename_and_delete_a_standalone_model(client):
    gid = _generate(client)
    assert client.patch(f"/api/v1/generations/{gid}", json={"name": "  My house "}).json()["name"] == "My house"
    assert _recent(client)[gid]["name"] == "My house"
    assert client.patch(f"/api/v1/generations/{gid}", json={"name": ""}).status_code == 422
    assert client.delete(f"/api/v1/generations/{gid}").status_code == 204
    assert gid not in _recent(client)
    assert client.get(f"/api/v1/generations/{gid}/artifacts/glb").status_code == 404  # gone for everyone
    assert client.delete(f"/api/v1/generations/{gid}").status_code == 404


def test_other_users_and_project_models_cannot_be_changed(client):
    gid = _generate(client)
    other = TestClient(app)  # a different logged-in user
    assert other.patch(f"/api/v1/generations/{gid}", json={"name": "x"}).status_code == 404
    assert other.delete(f"/api/v1/generations/{gid}").status_code == 404
    pid = client.post("/api/v1/projects/from-generation", json={"generation_id": gid, "name": "P"}).json()["project_id"]
    assert pid
    assert client.delete(f"/api/v1/generations/{gid}").status_code == 409  # belongs to a project now
    assert client.patch(f"/api/v1/generations/{gid}", json={"name": "x"}).status_code == 409
