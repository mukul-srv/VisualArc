from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from api.engine.adapters.dxf.reader import read_dxf
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
H = {"wall_height": 3000, "ceiling_height": 3000}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _upload(client, name):
    return client.post("/api/v1/uploads", content=(INPUT / name).read_bytes()).json()["upload_id"]


def _add(client, pid, name="fixture_a.dxf", floor="Ground", elev=0, **kw):
    body = {"upload_id": _upload(client, name), "floor_name": floor, "elevation": elev, **H, **kw}
    return client.post(f"{P}/{pid}/floors", json=body)


def _pid(client):
    r = client.post(P, json={"name": "House"})
    assert r.status_code == 201
    return r.json()["project_id"]


def test_two_floors_manifest_and_glb_at_elevation(client):
    pid = _pid(client)
    a = _add(client, pid, "fixture_a.dxf", "Ground", 0)
    b = _add(client, pid, "fixture_openings.dxf", "First", 3200.5)
    assert a.status_code == b.status_code == 201
    assert b.json()["floor"]["id"] == "floor-1"
    m = client.get(f"{P}/{pid}").json()
    assert m["name"] == "House"
    assert [f["id"] for f in m["floors"]] == ["floor-0", "floor-1"]
    assert m["floors"][1]["elevation"] == {"value": 3200.5, "unit": "mm", "source": "user_provided"}
    assert m["floors"][1]["generation_id"] == b.json()["generation_id"]
    # elevation provenance is user_provided: no elevation_defaulted warning
    assert "elevation_defaulted" not in {i["code"] for i in b.json()["issues"]}
    canon = client.get(b.json()["artifacts"]["canonical"]).json()["buildings"][0]["floors"][0]
    assert (canon["id"], canon["name"]) == ("floor-1", "First")
    assert canon["elevation"]["source"] == "user_provided"
    glb = client.get(b.json()["artifacts"]["glb"]).content
    scene = trimesh.load(trimesh.util.wrap_as_stream(glb), file_type="glb")
    assert scene.bounds[0][1] == pytest.approx(3.2005, abs=1e-6)  # model already at elevation


def test_duplicate_name_and_elevation_rejected_nothing_appended(client):
    pid = _pid(client)
    assert _add(client, pid).status_code == 201
    dup_name = _add(client, pid, floor=" ground ", elev=3000)
    dup_elev = _add(client, pid, floor="Other", elev=0)
    assert dup_name.status_code == dup_elev.status_code == 422
    assert "name" in dup_name.json()["detail"] and "elevation" in dup_elev.json()["detail"]
    assert len(client.get(f"{P}/{pid}").json()["floors"]) == 1


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_elevation_rejected_nothing_appended(client, token):
    pid = _pid(client)
    uid = _upload(client, "fixture_a.dxf")
    # raw body: the test client's json= cannot encode NaN/inf
    body = f'{{"upload_id": "{uid}", "floor_name": "G", "elevation": {token}, "wall_height": 3000, "ceiling_height": 3000}}'
    r = client.post(f"{P}/{pid}/floors", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert client.get(f"{P}/{pid}").json()["floors"] == []


def test_non_finite_bounded_height_rejected_on_generations(client):
    uid = _upload(client, "fixture_a.dxf")
    body = f'{{"upload_id": "{uid}", "wall_height": Infinity}}'
    r = client.post("/api/v1/generations", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["input"] == "inf"


def test_blocking_issue_is_409_and_nothing_appended(client):
    pid = _pid(client)
    r = client.post(
        f"{P}/{pid}/floors",
        json={"upload_id": _upload(client, "fixture_a.dxf"), "floor_name": "G", "elevation": 0},
    )
    assert r.status_code == 409 and r.json()["issues"]
    assert client.get(f"{P}/{pid}").json()["floors"] == []


def test_invalid_and_unknown_ids(client):
    assert client.get(f"{P}/../x").status_code in (404, 422)
    assert client.get(f"{P}/nothex").status_code == 404
    assert client.get(f"{P}/{'0' * 32}").status_code == 404
    r = client.post(
        f"{P}/{'0' * 32}/floors",
        json={"upload_id": "0" * 32, "floor_name": "G", "elevation": 0, **H},
    )
    assert r.status_code == 404
    pid = _pid(client)
    assert _add(client, pid).status_code == 201
    bad = client.post(f"{P}/{pid}/floors", json={"upload_id": "0" * 32, "floor_name": "X", "elevation": 5, **H})
    assert bad.status_code == 404
    assert client.post(P, json={"name": ""}).status_code == 422


def test_standalone_generation_unchanged(client):
    r = client.post("/api/v1/generations", json={"upload_id": _upload(client, "fixture_a.dxf"), **H})
    assert r.status_code == 201
    assert "elevation_defaulted" in {i["code"] for i in r.json()["issues"]}
    f = client.get(r.json()["artifacts"]["canonical"]).json()["buildings"][0]["floors"][0]
    assert (f["id"], f["name"], f["elevation"]["source"]) == ("floor-0", "Level 0", "defaulted")


def test_reader_floor_params():
    p = read_dxf(INPUT / "fixture_a.dxf", 3000, ceiling_height=3000, floor_id="floor-2", floor_name="Top", floor_elevation=6400)
    f = p.buildings[0].floors[0]
    assert (f.id, f.name, f.elevation.value, f.elevation.source) == ("floor-2", "Top", 6400, "user_provided")
    assert f.ceilings[0].elevation.value == 9400
    assert "elevation_defaulted" not in {i.code for i in p.issues}


def test_concurrent_floor_adds_keep_both_floors(client):
    from concurrent.futures import ThreadPoolExecutor

    pid = _pid(client)
    ups = [_upload(client, "fixture_a.dxf") for _ in range(2)]

    def add(i):
        body = {"upload_id": ups[i], "floor_name": f"F{i}", "elevation": i * 3000, **H}
        return client.post(f"{P}/{pid}/floors", json=body).status_code

    with ThreadPoolExecutor(2) as ex:
        assert list(ex.map(add, range(2))) == [201, 201]
    floors = client.get(f"{P}/{pid}").json()["floors"]
    assert sorted(f["id"] for f in floors) == ["floor-0", "floor-1"]
    assert len({f["generation_id"] for f in floors}) == 2


def test_import_projects_is_idempotent(client, tmp_path):
    import json

    from api.importer import import_projects

    pid = "a" * 32
    d = tmp_path / "projects" / pid
    d.mkdir(parents=True)
    (d / "project.json").write_text(json.dumps({"id": pid, "name": "Old", "floors": []}))
    assert import_projects() == (1, 0)
    assert import_projects() == (0, 1)
    assert client.get(f"{P}/{pid}").json()["name"] == "Old"
