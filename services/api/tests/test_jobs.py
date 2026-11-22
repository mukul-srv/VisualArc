"""Generation jobs: stage progression, failure reporting, restart recovery, access."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.db import JobRow, session
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
_REAL_SUBMIT = jobs.submit
H = {"wall_height": 3000, "ceiling_height": 3000}


@pytest.fixture(autouse=True)
def manual_runner(tmp_path, monkeypatch):
    """Jobs stay queued until a test runs them with `jobs.execute`, so stages are deterministic."""
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)


def _upload(c, name="fixture_a.dxf"):
    return c.post("/api/v1/uploads", content=(INPUT / name).read_bytes()).json()["upload_id"]


def _status(c, jid):
    return c.get(f"/api/v1/jobs/{jid}")


def _start(c, **kw):
    return c.post("/api/v1/jobs/generations", json={"upload_id": kw.pop("up", None) or _upload(c), **H, **kw})


def test_stage_progression(monkeypatch):
    c = TestClient(app)
    r = _start(c)
    assert r.status_code == 202
    jid = r.json()["job_id"]
    s = _status(c, jid).json()
    assert (s["status"], s["stage"], s["progress"]) == ("queued", "queued", 0)

    seen = []
    orig = jobs._set

    def spy(job_id, **f):
        if "stage" in f:
            seen.append((f["stage"], f["progress"]))
        orig(job_id, **f)

    monkeypatch.setattr(jobs, "_set", spy)
    jobs.execute(jid)
    assert seen == [("parsing", 10), ("building-model", 50), ("exporting", 75), ("done", 100)]
    s = _status(c, jid).json()
    assert (s["status"], s["stage"], s["progress"], s["error"]) == ("succeeded", "done", 100, None)
    assert c.get(s["result"]["artifacts"]["glb"]).status_code == 200
    jobs.execute(jid)  # already finished: no-op
    assert _status(c, jid).json()["status"] == "succeeded"


def test_floor_job_adds_floor_and_failure_is_reported():
    c = TestClient(app)
    pid = c.post(P, json={"name": "H"}).json()["project_id"]
    body = {"upload_id": _upload(c), "floor_name": "Ground", "elevation": 0, **H}
    jid = c.post(f"/api/v1/jobs/projects/{pid}/floors", json=body).json()["job_id"]
    jobs.execute(jid)
    assert _status(c, jid).json()["status"] == "succeeded"
    assert len(c.get(f"{P}/{pid}").json()["floors"]) == 1
    # same name again: the engine's 422 message lands on the job
    jid = c.post(f"/api/v1/jobs/projects/{pid}/floors", json=body).json()["job_id"]
    jobs.execute(jid)
    s = _status(c, jid).json()
    assert s["status"] == "failed" and "already exists" in s["error"]
    assert len(c.get(f"{P}/{pid}").json()["floors"]) == 1


def test_unexpected_error_and_blocking_issues(monkeypatch):
    c = TestClient(app)
    jid = _start(c).json()["job_id"]

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(jobs, "run_generation", boom)
    jobs.execute(jid)
    s = _status(c, jid).json()
    assert s["status"] == "failed" and "kaboom" in s["error"]

    monkeypatch.setattr(jobs, "run_generation", lambda *a, **k: (None, [{"code": "X", "severity": "blocking"}]))
    jid = _start(c).json()["job_id"]
    jobs.execute(jid)
    s = _status(c, jid).json()
    assert s["status"] == "failed" and "Blocking" in s["error"] and s["result"]["issues"][0]["code"] == "X"


def test_restart_recovery_fails_running_and_queued_only():
    c = TestClient(app)
    queued, running, done = (_start(c).json()["job_id"] for _ in range(3))
    with session() as db:
        db.get(JobRow, running).status = "running"
        db.get(JobRow, done).status = "succeeded"
        db.commit()
    assert jobs.recover_jobs() >= 2
    for jid, want in ((queued, "failed"), (running, "failed"), (done, "succeeded")):
        assert _status(c, jid).json()["status"] == want
    assert _status(c, running).json()["error"] == jobs.RESTART_ERROR


def test_access_rules():
    owner, viewer, editor, stranger = (TestClient(app) for _ in range(4))
    anon = TestClient(app)
    anon.cookies.clear()
    pid = owner.post(P, json={"name": "H"}).json()["project_id"]
    for c, role in ((viewer, "viewer"), (editor, "editor")):
        email = c.get("/api/v1/auth/me").json()["email"]
        assert owner.put(f"{P}/{pid}/access", json={"email": email, "role": role}).status_code == 200
    body = lambda c: {"upload_id": _upload(c), "floor_name": "G", "elevation": 0, **H}

    assert anon.post(f"/api/v1/jobs/projects/{pid}/floors", json=body(owner)).status_code == 401
    assert viewer.post(f"/api/v1/jobs/projects/{pid}/floors", json=body(viewer)).status_code == 404
    assert stranger.post(f"/api/v1/jobs/projects/{pid}/floors", json=body(stranger)).status_code == 404
    # nobody can start from another user's upload
    assert editor.post("/api/v1/jobs/generations", json={"upload_id": _upload(owner), **H}).status_code == 404

    jid = editor.post(f"/api/v1/jobs/projects/{pid}/floors", json=body(editor)).json()["job_id"]
    for c, code in ((editor, 200), (owner, 200), (viewer, 200), (stranger, 404)):
        assert _status(c, jid).status_code == code
    assert _status(anon, jid).status_code == 401
    # a standalone generation job is private to its starter
    g = _start(owner).json()["job_id"]
    assert _status(viewer, g).status_code == 404 and _status(owner, g).status_code == 200


def test_real_worker_runs_job(monkeypatch):
    import time

    monkeypatch.setattr(jobs, "submit", _REAL_SUBMIT)
    c = TestClient(app)
    jid = _start(c).json()["job_id"]
    for _ in range(100):
        s = _status(c, jid).json()
        if s["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert s["status"] == "succeeded", s
