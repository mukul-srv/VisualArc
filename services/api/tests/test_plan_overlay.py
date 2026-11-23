"""Plan overlay endpoint: source linework + model footprints for one project floor, role-gated, bounded."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.engine.settings import DEFAULTS
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
H = {"wall_height": 3000, "ceiling_height": 3000}


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))


def _project(c):
    pid = c.post(P, json={"name": "O"}).json()["project_id"]
    up = c.post("/api/v1/uploads", content=(INPUT / "fixture_openings.dxf").read_bytes()).json()["upload_id"]
    r = c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": "G", "elevation": 0, **H})
    assert r.status_code == 201, r.text
    return pid, r.json()["floor"]["id"]


def test_overlay_has_source_lines_and_model_footprints_in_the_same_coordinates():
    c = TestClient(app)
    pid, fid = _project(c)
    r = c.get(f"{P}/{pid}/floors/{fid}/plan")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["unit"] == "mm" and not d["source"]["truncated"] and d["source"]["total"] == len(d["source"]["segments"])
    walls = [s for s in d["source"]["segments"] if s["wall"]]
    assert walls and d["model"]["walls"] and d["model"]["openings"] and d["model"]["boundaries"]
    # every built wall's centreline lies inside the bounding box of the drawn wall lines (same frame)
    xs = [v for s in walls for v in s["p"][0::2]]
    ys = [v for s in walls for v in s["p"][1::2]]
    for w in d["model"]["walls"]:
        for x, y in (w["start"], w["end"]):
            assert min(xs) - 1e-6 <= x <= max(xs) + 1e-6 and min(ys) - 1e-6 <= y <= max(ys) + 1e-6


def test_overlay_is_cut_and_says_so_when_the_drawing_is_larger_than_the_cap(monkeypatch):
    import api.plan_overlay as po

    monkeypatch.setattr(po, "DEFAULTS", type(DEFAULTS)(**{**DEFAULTS.__dict__, "plan_overlay_max_segments": 5}))
    c = TestClient(app)
    pid, fid = _project(c)
    d = c.get(f"{P}/{pid}/floors/{fid}/plan").json()
    assert d["source"]["truncated"] and len(d["source"]["segments"]) == 5 and d["source"]["total"] > 5
    assert all(s["wall"] for s in d["source"]["segments"])  # the cut keeps the wall layers first


def test_overlay_roles():
    owner, viewer, stranger = (TestClient(app) for _ in range(3))
    pid, fid = _project(owner)
    email = viewer.get("/api/v1/auth/me").json()["email"]
    owner.put(f"{P}/{pid}/access", json={"email": email, "role": "viewer"})
    assert viewer.get(f"{P}/{pid}/floors/{fid}/plan").status_code == 200
    assert stranger.get(f"{P}/{pid}/floors/{fid}/plan").status_code == 404
    assert owner.get(f"{P}/{pid}/floors/nope/plan").status_code == 404
