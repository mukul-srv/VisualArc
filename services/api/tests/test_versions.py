"""Ownership (404 for everyone else), immutable versions, restore, soft delete."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
H = {"wall_height": 3000, "ceiling_height": 3000}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


@pytest.fixture
def other(client):  # a second, separately logged-in account
    return TestClient(app)


def _upload(c, name="fixture_a.dxf"):
    return c.post("/api/v1/uploads", content=(INPUT / name).read_bytes()).json()["upload_id"]


def _floor(c, pid, name, elev, up=None, **kw):
    body = {"upload_id": up or _upload(c), "floor_name": name, "elevation": elev, **H, **kw}
    return c.post(f"{P}/{pid}/floors", json=body)


@pytest.fixture
def proj(client):
    pid = client.post(P, json={"name": "House"}).json()["project_id"]
    r = _floor(client, pid, "Ground", 0, building_type="commercial")
    assert r.status_code == 201
    return pid, r.json()


def test_other_user_gets_404_everywhere(client, other, proj):
    pid, floor = proj
    up = _upload(client)
    gid = floor["generation_id"]
    art = floor["artifacts"]["glb"]
    assert client.get(art).status_code == 200
    calls = [
        other.get(f"{P}/{pid}"),
        other.get(f"{P}/{pid}?version=1"),
        other.patch(f"{P}/{pid}", json={"name": "x"}),
        other.delete(f"{P}/{pid}"),
        other.get(f"{P}/{pid}/versions"),
        other.get(f"{P}/{pid}/versions/1"),
        other.post(f"{P}/{pid}/versions/1/restore"),
        _floor(other, pid, "Hack", 5000, up=_upload(other)),  # foreign project
        _floor(other, pid, "Hack", 5000, up=up),  # foreign upload on foreign project
        other.post("/api/v1/generations", json={"upload_id": up, **H}),  # foreign upload
        other.post(f"/api/v1/uploads/{up}/split", json={
            "project_name": "x", "floors": [{"key": "a", "exclude": True}]}),
        other.get(art),
        other.get(f"/api/v1/generations/{gid}/artifacts/meta"),
    ]
    assert [r.status_code for r in calls] == [404] * len(calls)
    # own upload on a foreign project, and a foreign upload on own project: 404 too
    mine = client.post(P, json={"name": "Mine"}).json()["project_id"]
    assert _floor(client, mine, "A", 0, up=_upload(other)).status_code == 404
    assert other.get(P).json() == []
    assert other.get("/api/v1/generations/recent").json() == []
    # the owner is unaffected and nothing was changed
    assert client.get(f"{P}/{pid}").json()["name"] == "House"
    assert len(client.get(f"{P}/{pid}/versions").json()) == 2


def test_ownerless_rows_are_inaccessible(client, proj):
    from api.db import GenerationRow, ProjectRow, UploadRow, session

    pid, floor = proj
    up = _upload(client)
    with session() as db:
        for m, i in ((ProjectRow, pid), (GenerationRow, floor["generation_id"]), (UploadRow, up)):
            db.get(m, i).owner_id = None
        db.commit()
    assert client.get(f"{P}/{pid}").status_code == 404
    assert client.get(floor["artifacts"]["glb"]).status_code == 404
    assert client.post("/api/v1/generations", json={"upload_id": up, **H}).status_code == 404


def test_every_mutation_writes_a_version(client, proj):
    pid, _ = proj
    assert _floor(client, pid, "First", 3000).status_code == 201
    vs = client.get(f"{P}/{pid}/versions").json()  # newest first
    assert [v["number"] for v in vs] == [3, 2, 1]
    assert [v["floor_count"] for v in vs] == [2, 1, 0]
    v3 = client.get(f"{P}/{pid}/versions/3").json()
    snap = v3["snapshot"]
    assert snap["generation_ids"] == [f["generation_id"] for f in snap["floors"]]
    assert snap["params"]["floor-0"]["building_type"] == {"value": "commercial", "source": "user_provided"}
    assert snap["params"]["floor-0"]["door_height"]["source"] == "defaulted"
    assert snap["params"]["floor-0"]["wall_height"] == {"value": 3000, "source": "user_provided"}
    cur = client.get(f"{P}/{pid}").json()
    assert cur["version"] == 3 and cur["floors"] == snap["floors"]  # latest version == current
    assert client.get(f"{P}/{pid}/versions/9").status_code == 404
    # a rejected add writes nothing
    assert _floor(client, pid, "First", 4000).status_code == 422
    assert len(client.get(f"{P}/{pid}/versions").json()) == 3


def test_restore_makes_new_version_and_keeps_history(client, proj):
    pid, floor = proj
    _floor(client, pid, "First", 3000)
    before = {n: client.get(f"{P}/{pid}/versions/{n}").json() for n in (1, 2, 3)}
    r = client.post(f"{P}/{pid}/versions/2/restore")
    assert r.status_code == 201 and r.json()["number"] == 4
    cur = client.get(f"{P}/{pid}").json()
    assert cur["version"] == 4 and [f["name"] for f in cur["floors"]] == ["Ground"]
    assert client.get(f"{P}/{pid}?version=3").json()["floors"][1]["name"] == "First"
    for n in (1, 2, 3):  # old versions untouched
        assert client.get(f"{P}/{pid}/versions/{n}").json() == before[n]
    assert client.get(f"{P}/{pid}/versions/4").json()["message"] == "Restored version 2"
    assert client.get(floor["artifacts"]["glb"]).status_code == 200  # blobs kept
    # adding after a restore continues from the restored state
    assert _floor(client, pid, "Second", 3000).status_code == 201
    assert client.get(f"{P}/{pid}").json()["version"] == 5


def test_rename_and_soft_delete(client, other, proj, tmp_path):
    pid, floor = proj
    assert client.patch(f"{P}/{pid}", json={"name": " Villa "}).status_code == 200
    row = next(p for p in client.get(P).json() if p["id"] == pid)
    assert (row["name"], row["floor_count"], row["version"], row["thumbnail"]) == ("Villa", 1, 2, None)
    assert client.delete(f"{P}/{pid}").status_code == 204
    assert client.get(P).json() == []
    assert client.get(f"{P}/{pid}").status_code == 404
    assert _floor(client, pid, "More", 3000).status_code == 404
    assert client.get("/api/v1/generations/recent").json() == []
    from api.db import ProjectRow, session

    with session() as db:
        assert db.get(ProjectRow, pid).deleted_at is not None  # row kept
    assert (tmp_path / "generations" / floor["generation_id"] / "model.glb").is_file()  # blobs kept


def test_dashboard_and_recent_generations(client, proj):
    pid, floor = proj
    standalone = client.post("/api/v1/generations", json={"upload_id": _upload(client), **H}).json()
    rec = client.get("/api/v1/generations/recent").json()
    assert [g["generation_id"] for g in rec] == [standalone["generation_id"], floor["generation_id"]]
    assert (rec[1]["project_name"], rec[1]["floor_name"], rec[1]["project_id"]) == ("House", "Ground", pid)
    assert rec[0]["project_id"] is None
    lst = client.get(P).json()
    assert [(p["name"], p["floor_count"], p["version"]) for p in lst] == [("House", 1, 2)]
    for _ in range(11):
        client.post("/api/v1/generations", json={"upload_id": _upload(client), **H})
    assert len(client.get("/api/v1/generations/recent").json()) == 10


def test_import_owner_unknown_email(client, tmp_path):
    from api.importer import import_projects

    pid = "b" * 32
    d = tmp_path / "projects" / pid
    d.mkdir(parents=True)
    (d / "project.json").write_text(json.dumps({"id": pid, "name": "Old", "floors": []}))
    with pytest.raises(ValueError):
        import_projects("nobody@test.example")
    assert import_projects() == (1, 0)  # nothing was imported by the failed call
