"""Project parameters with provenance, slabs and parameter-driven regeneration (Phase 1/07)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.geometry3d.extrude import build_meshes
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
A = INPUT / "fixture_a.dxf"


def test_defaults_are_tagged_and_slab_sits_under_the_floor():
    p = read_dxf(A, building_type="commercial")
    assert p.parameters["slab_thickness"].model_dump() == {"value": 250.0, "unit": "mm", "source": "defaulted"}
    assert p.parameters["roof_type"].value == "flat" and p.parameters["roof_pitch"].unit == "deg"
    assert "slab_thickness_defaulted" in {i.code for i in p.issues}
    f = p.buildings[0].floors[0]
    assert len(f.slabs) == len(f.boundaries) and f.slabs[0].thickness.source == "defaulted"
    z = build_meshes(f)[f.slabs[0].id].bounds[:, 2]
    assert z.tolist() == [f.elevation.value - 250, f.elevation.value]


def test_user_values_override_and_tag_user_provided():
    p = read_dxf(A, building_type="residential", ceiling_height=2500, params={"slab_thickness": 300, "roof_type": "flat"})
    f = p.buildings[0].floors[0]
    assert f.slabs[0].thickness.value == 300 and f.slabs[0].thickness.source == "user_provided"
    assert f.ceiling_height.value == 2500
    assert {k: v.source for k, v in p.parameters.items() if v.source == "user_provided"}.keys() == {
        "ceiling_height", "slab_thickness", "roof_type"}
    assert "slab_thickness_defaulted" not in {i.code for i in p.issues}


def test_no_preset_no_user_slab_means_no_slab_and_bad_values_rejected():
    assert not read_dxf(A, 3000, ceiling_height=3000).buildings[0].floors[0].slabs
    with pytest.raises(ValueError, match="slab thickness"):
        read_dxf(A, building_type="residential", params={"slab_thickness": 0})
    with pytest.raises(ValueError, match="unknown parameters"):
        read_dxf(A, building_type="residential", params={"nope": 1})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)  # run by hand below
    return TestClient(app)


def _canon(c, gid):
    return c.get(f"/api/v1/generations/{gid}/artifacts/canonical").json()["buildings"][0]["floors"][0]


def _project(c):
    pid = c.post(P, json={"name": "H"}).json()["project_id"]
    up = c.post("/api/v1/uploads", content=A.read_bytes()).json()["upload_id"]
    r = c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": "Ground", "elevation": 0})
    assert r.status_code == 201
    return pid


def _change(c, pid, **body):
    r = c.post(f"/api/v1/jobs/projects/{pid}/parameters", json=body)
    assert r.status_code == 202, r.text
    jobs.execute(r.json()["job_id"])
    return c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()


def test_parameter_job_flow(client):
    c = client
    pid = _project(c)
    got = c.get(f"{P}/{pid}/parameters").json()
    assert got["ceiling_height"] == {"value": 2700.0, "unit": "mm", "source": "defaulted"}
    old = c.get(f"{P}/{pid}").json()["floors"][0]["generation_id"]

    job = _change(c, pid, ceiling_height=2400, slab_thickness=300)
    assert job["status"] == "succeeded"
    m = c.get(f"{P}/{pid}").json()
    assert m["version"] == 3 and m["floors"][0]["generation_id"] != old  # created, add floor, params
    canon = _canon(c, m["floors"][0]["generation_id"])
    assert canon["ceiling_height"] == {"value": 2400.0, "unit": "mm", "source": "user_provided"}
    assert canon["ceilings"][0]["height"]["source"] == "user_provided"  # shown by the inspector
    assert canon["slabs"][0]["thickness"] == {"value": 300.0, "unit": "mm", "source": "user_provided"}
    got = c.get(f"{P}/{pid}/parameters").json()
    assert got["ceiling_height"]["source"] == "user_provided" and got["roof_type"]["source"] == "defaulted"

    # null resets to the preset default
    _change(c, pid, ceiling_height=None)
    m = c.get(f"{P}/{pid}").json()
    assert _canon(c, m["floors"][0]["generation_id"])["ceiling_height"]["source"] == "defaulted"
    assert c.get(f"{P}/{pid}/parameters").json()["slab_thickness"]["value"] == 300.0

    # a floor added later inherits the project's parameters
    up = c.post("/api/v1/uploads", content=A.read_bytes()).json()["upload_id"]
    r = c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": "Up", "elevation": 3000})
    assert _canon(c, r.json()["generation_id"])["slabs"][0]["thickness"]["value"] == 300.0

    # restoring version 3 restores that parameter set
    c.post(f"{P}/{pid}/versions/3/restore")
    assert c.get(f"{P}/{pid}/parameters").json()["ceiling_height"]["value"] == 2400.0


def test_invalid_empty_and_read_only(client):
    c = client
    pid = _project(c)
    assert c.post(f"/api/v1/jobs/projects/{pid}/parameters", json={}).status_code == 422
    assert c.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"roof_pitch": 90}).status_code == 422
    assert c.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"roof_type": "dome"}).status_code == 422
    assert c.post(f"/api/v1/jobs/projects/{'0' * 32}/parameters", json={"stair_rise": 170}).status_code == 404
