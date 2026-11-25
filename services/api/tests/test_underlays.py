"""Trace-assist underlays (Phase 1/25): image checks, user-given calibration, empty floor, traced walls."""

import dataclasses
import io
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api import jobs, underlays
from api.engine.settings import DEFAULTS
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"


def _png(w=400, h=300, fmt="PNG", mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (w, h), "white").save(out, fmt)
    return out.getvalue()


def test_calibration_is_user_provided_and_checked():
    c = underlays.calibration((0, 0), (300, 400), 5000)  # 500 px apart
    assert c["mm_per_px"] == pytest.approx(10) and c["source"] == "user_provided"
    with pytest.raises(ValueError, match="px apart"):
        underlays.calibration((1, 1), (2, 2), 1000)
    for bad in (0, -5, math.inf, math.nan):
        with pytest.raises(ValueError, match="positive"):
            underlays.calibration((0, 0), (100, 0), bad)


def test_images_are_judged_by_content_and_capped(monkeypatch):
    png, w, h = underlays.normalize(_png())
    assert (w, h) == (400, 300) and png[:8] == b"\x89PNG\r\n\x1a\n"
    jpg, w, h = underlays.normalize(_png(fmt="JPEG"))  # JPEG is re-encoded as PNG
    assert jpg[:4] == b"\x89PNG"
    rgba, *_ = underlays.normalize(_png(mode="RGBA"))
    assert Image.open(io.BytesIO(rgba)).mode == "RGB"  # alpha is dropped
    for bad, msg in ((_png(fmt="GIF"), "only PNG"), (b"MZ\x90\x00 not an image", "not a readable"), (b"", "not a readable")):
        with pytest.raises(ValueError, match=msg):
            underlays.normalize(bad)
    small = dataclasses.replace(DEFAULTS, underlay_max_pixels=1000, underlay_max_bytes=2000)
    monkeypatch.setattr(underlays, "DEFAULTS", small)
    with pytest.raises(ValueError, match="pixels"):
        underlays.normalize(_png(100, 100))  # a small file with too many pixels: the decompression-bomb case
    with pytest.raises(ValueError, match="MB"):
        underlays.normalize(b"x" * 3000)
    monkeypatch.setattr(underlays, "DEFAULTS", dataclasses.replace(DEFAULTS, underlay_max_side_px=100))
    _, w, h = underlays.normalize(_png(400, 300))
    assert (w, h) == (100, 75)  # downscaled, aspect kept


def test_a_pdf_page_is_rendered_as_the_picture():
    for name in ("fixture_raster.pdf", "fixture_plan.pdf"):
        png, w, h = underlays.normalize((INPUT / name).read_bytes())
        assert w > 100 and h > 100 and png[:4] == b"\x89PNG"
    with pytest.raises(ValueError, match="could not be opened"):
        underlays.normalize(b"%PDF-1.4\nbroken")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def _trace(c, **q):
    return c.post("/api/v1/trace/floors", params={"floor_name": "Ground", "project_name": "Traced", **q}, content=_png())


def test_empty_floor_from_an_image_then_calibrate_and_trace(client):
    r = _trace(client, filename="scan.png")
    assert r.status_code == 201, r.text
    body = r.json()
    pid, fid = body["project_id"], body["floor"]["id"]
    assert body["floor"]["underlay"]["calibration"] is None
    assert "trace_floor_empty" in {i["code"] for i in body["issues"]}  # empty is reported, not hidden
    m = client.get(f"{P}/{pid}").json()
    assert m["floors"][0]["underlay"]["width_px"] == 400
    img = client.get(f"{P}/{pid}/floors/{fid}/underlay")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    plan = client.get(f"{P}/{pid}/floors/{fid}/plan").json()
    assert plan["source"]["segments"] == [] and plan["model"]["walls"] == []
    assert plan["underlay"]["url"].endswith("/underlay") and plan["underlay"]["calibration"] is None
    # two clicks on the image + a real distance
    url = f"{P}/{pid}/floors/{fid}/underlay/calibration"
    assert client.put(url, json={"p1": [0, 0], "p2": [3, 4], "distance_mm": 1000}).status_code == 422  # too close
    assert client.put(url, json={"p1": [0, 0], "p2": [900, 0], "distance_mm": 1000}).status_code == 422  # off the image
    assert client.put(url, json={"p1": [0, 0], "p2": [100, 0], "distance_mm": -1}).status_code == 422
    n = len(client.get(f"{P}/{pid}/versions").json())
    r = client.put(url, json={"p1": [0, 100], "p2": [300, 350], "distance_mm": 5000})
    assert r.status_code == 422  # (300, 350) is below the 300 px high image
    r = client.put(url, json={"p1": [0, 100], "p2": [300, 100], "distance_mm": 6000})
    assert r.status_code == 200 and r.json()["calibration"]["mm_per_px"] == pytest.approx(20)
    cal = client.get(f"{P}/{pid}").json()["floors"][0]["underlay"]["calibration"]
    assert cal["source"] == "user_provided" and cal["distance_mm"] == 6000
    assert len(client.get(f"{P}/{pid}/versions").json()) == n + 1
    # trace a wall with the normal editing ops; the server builds the floor from them
    edit = {"op": "add_wall", "id": "t1", "start": [0, 0], "end": [4000, 0], "thickness": 200}
    jid = client.put(f"/api/v1/jobs/projects/{pid}/floors/{fid}/edits", json={"edits": [edit]}).json()["job_id"]
    jobs.execute(jid)
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["stage"] == "done", job
    plan = client.get(f"{P}/{pid}/floors/{fid}/plan").json()
    assert len(plan["model"]["walls"]) == 1 and plan["model"]["walls"][0]["provenance"] == "user_modified"
    assert plan["underlay"]["calibration"]["source"] == "user_provided"  # kept through the replay


def test_access_and_bad_input(client):
    assert client.post("/api/v1/trace/floors", params={"floor_name": "G"}, content=_png()).status_code == 422  # no project
    assert client.post("/api/v1/trace/floors", params={"floor_name": "G", "project_name": "x", "project_id": "y"},
                       content=_png()).status_code == 422
    assert client.post("/api/v1/trace/floors", params={"floor_name": "G", "project_name": "x"}, content=b"").status_code == 422
    assert client.post("/api/v1/trace/floors", params={"floor_name": "G", "project_name": "x"},
                       content=b"GIF89a....").status_code == 422
    r = _trace(client)
    pid, fid = r.json()["project_id"], r.json()["floor"]["id"]
    other = TestClient(app)  # another user
    assert other.get(f"{P}/{pid}/floors/{fid}/underlay").status_code == 404
    assert other.put(f"{P}/{pid}/floors/{fid}/underlay/calibration",
                     json={"p1": [0, 0], "p2": [100, 0], "distance_mm": 1000}).status_code == 404
    assert other.post("/api/v1/trace/floors", params={"floor_name": "G", "project_id": pid}, content=_png()).status_code == 404
    # a second traced floor joins the project
    again = client.post("/api/v1/trace/floors", params={"floor_name": "First", "project_id": pid, "elevation": 3000}, content=_png())
    assert again.status_code == 201 and len(client.get(f"{P}/{pid}").json()["floors"]) == 2
