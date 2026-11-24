"""Guided review draft job: issues + stats + overlay per floor, nothing stored."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api import jobs
from api.db import GenerationRow, session
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
H = {"wall_height": 3000, "ceiling_height": 3000}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)


def _upload(c, name="fixture_a.dxf"):
    return c.post("/api/v1/uploads", content=(INPUT / name).read_bytes()).json()["upload_id"]


def _draft(c, up, **body):
    r = c.post(f"/api/v1/jobs/uploads/{up}/draft", json=body)
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    jobs.execute(jid)
    return c.get(f"/api/v1/jobs/{jid}").json()


def _generations():
    with session() as db:
        return db.scalar(select(func.count()).select_from(GenerationRow))


def test_draft_returns_issues_stats_overlay_and_stores_nothing(tmp_path):
    c = TestClient(app)
    before = _generations()
    j = _draft(c, _upload(c), **H)
    assert j["status"] == "succeeded" and j["result"]["blocking"] is False
    [fl] = j["result"]["floors"]
    assert fl["stats"]["walls"] > 0 and fl["stats"]["rooms"] > 0 and fl["stats"]["area"] > 0
    assert fl["overlay"]["model"]["walls"] and fl["overlay"]["source"]["segments"]
    assert _generations() == before
    assert not (tmp_path / "generations").exists()


def test_blocked_draft_still_returns_issues():
    c = TestClient(app)
    import io

    import ezdxf
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 0
    for a, b in [((0, 0), (4, 0)), ((0, 0.2), (4, 0.2))]:
        doc.modelspace().add_line(a, b, dxfattribs={"layer": "A-WALL"})
    buf = io.StringIO()
    doc.write(buf)
    up = c.post("/api/v1/uploads", content=buf.getvalue().encode()).json()["upload_id"]
    j = _draft(c, up)  # no units: blocking
    assert j["status"] == "succeeded" and j["result"]["blocking"] is True
    assert "units_missing" in {i["code"] for i in j["result"]["floors"][0]["issues"]}


def test_draft_split_rows():
    c = TestClient(app)
    up = _upload(c, "fixture_f.dxf")
    rows = [{"key": "cluster-1", "name": "G", "offset_x": 0, "offset_y": 0},
            {"key": "cluster-2", "name": "F1", "offset_x": 0, "offset_y": 0, "elevation": 3000}]
    j = _draft(c, up, floors=rows, **H)
    assert j["status"] == "succeeded"
    assert [f["name"] for f in j["result"]["floors"]] == ["G", "F1"]


def test_draft_owner_only():
    owner, other = TestClient(app), TestClient(app)  # each client is a fresh user
    up = _upload(owner)
    assert other.post(f"/api/v1/jobs/uploads/{up}/draft", json=H).status_code == 404
    assert owner.post("/api/v1/jobs/uploads/" + "0" * 32 + "/draft", json=H).status_code == 404
    assert owner.post(f"/api/v1/jobs/uploads/{up}/draft", json=H).status_code == 202
