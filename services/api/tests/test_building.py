"""Building assembly (Phase 1/13): stair pairing, alignment check, issues, offsets, API roles."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.building import FloorData, check_alignment, check_stairs, effective_pairings
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
H = {"wall_height": 3000, "ceiling_height": 3000, "stair_rise": 160, "stair_run": 250}
REF = ("lower_floor", "lower_stair", "upper_floor", "upper_stair")


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))


def _sq(x, y, w=1000, h=1000):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _fd(id_, elev, stairs, bbox=(0, 0, 10000, 8000), rise=3200.0, finished=None):
    return FloorData(
        id=id_, name=id_, elevation=elev, finished=elev + 200 if finished is None else finished,
        top=elev + 3200, generation_id="g", roof=False, offset=(0, 0), offset_source="defaulted",
        bbox=bbox, area=0, rooms=0,
        stairs=[{"id": s, "polygon": p, "total_rise": rise} for s, p in stairs])


def test_auto_pair_by_overlap_one_to_one():
    a = _fd("a", 0, [("s1", _sq(0, 0)), ("s2", _sq(5000, 0))])
    b = _fd("b", 3200, [("t2", _sq(5100, 0)), ("t1", _sq(100, 0)), ("far", _sq(9000, 7000))])
    pairs, issues = effective_pairings([a, b], [])
    assert {(p["lower_stair"], p["upper_stair"], p["status"]) for p in pairs} == {
        ("s1", "t1", "auto"), ("s2", "t2", "auto")} and not issues


def test_rejected_and_confirmed_are_kept_over_auto():
    a = _fd("a", 0, [("s1", _sq(0, 0))])
    b = _fd("b", 3200, [("t1", _sq(0, 0)), ("t2", _sq(5000, 0))])
    ref = {"lower_floor": "a", "lower_stair": "s1", "upper_floor": "b", "upper_stair": "t1"}
    pairs, _ = effective_pairings([a, b], [{**ref, "status": "rejected"}])
    assert [p["status"] for p in pairs] == ["rejected"]  # not proposed again
    pairs, _ = effective_pairings([a, b], [{**ref, "upper_stair": "t2", "status": "confirmed"}])
    assert [(p["upper_stair"], p["status"]) for p in pairs] == [("t2", "confirmed")]
    # a saved pair whose stair vanished is dropped with an explicit issue
    _, issues = effective_pairings([a, _fd("b", 3200, [])], [{**ref, "status": "confirmed"}])
    assert [i["code"] for i in issues] == ["pairing_stale"]


def test_stair_issues_unpaired_rise_and_top_floor():
    a = _fd("a", 0, [("s1", _sq(0, 0)), ("lost", _sq(5000, 5000))])
    b = _fd("b", 3000, [("t1", _sq(0, 0))], finished=3200)  # finished gap 3000 != rise 3200
    pairs, _ = effective_pairings([a, b], [])
    got = {(i["code"], i["severity"]) for i in check_stairs([a, b], pairs)}
    assert got == {("stair_unpaired", "warning"), ("stair_rise_mismatch", "warning"),
                   ("stair_no_floor_above", "info")}


def test_alignment_warns_for_offset_and_not_for_aligned_or_smaller_floor():
    a = _fd("a", 0, [])
    assert not check_alignment([a, _fd("b", 1, [], bbox=(0, 0, 10000, 8000))])
    assert not check_alignment([a, _fd("b", 1, [], bbox=(1000, 1000, 6000, 5000))])  # inside
    (i,) = check_alignment([a, _fd("b", 1, [], bbox=(500, 0, 10500, 8000))])  # same size, shifted
    assert i["code"] == "floor_alignment_mismatch" and "-500" in i["message"]
    (i,) = check_alignment([a, _fd("b", 1, [], bbox=(20000, 0, 30000, 8000))])  # disjoint
    assert i["severity"] == "warning"
    assert check_alignment([a, _fd("b", 1, [], bbox=None)])[0]["code"] == "floor_no_outline"
    # a zero-area outline (one line) is reported as not comparable, never as a false mismatch
    assert [i["code"] for i in check_alignment([a, _fd("b", 1, [], bbox=(0, 0, 10000, 0))])] == ["floor_no_outline"]


# --- API ---

def _floor(c, pid, name, elev):
    up = c.post("/api/v1/uploads", content=(INPUT / "fixture_stairs.dxf").read_bytes()).json()["upload_id"]
    r = c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": name, "elevation": elev, **H})
    assert r.status_code == 201, r.text
    return r.json()["floor"]


@pytest.fixture
def proj():
    c = TestClient(app)
    pid = c.post(P, json={"name": "B"}).json()["project_id"]
    return c, pid, _floor(c, pid, "Ground", 0), _floor(c, pid, "First", 3200)


def _b(c, pid):
    r = c.get(f"{P}/{pid}/building")
    assert r.status_code == 200, r.text
    return r.json()


def test_building_api_floors_pairs_stats_and_clean_issues(proj):
    c, pid, g, f = proj
    b = _b(c, pid)
    assert [x["id"] for x in b["floors"]] == [g["id"], f["id"]]
    assert b["floors"][0]["offset"] == {"x": 0, "y": 0, "unit": "mm", "source": "defaulted"}
    assert [p["status"] for p in b["pairings"]] == ["auto"]
    assert b["pairings"][0]["overlap"] == pytest.approx(1)
    assert b["stats"]["floor_count"] == 2 and b["stats"]["stair_count"] == 2
    assert [i["code"] for i in b["issues"]] == ["stair_no_floor_above"]  # aligned, paired, rise = gap


def test_rise_mismatch_when_elevation_gap_differs():
    c = TestClient(app)
    pid = c.post(P, json={"name": "B"}).json()["project_id"]
    _floor(c, pid, "Ground", 0)
    _floor(c, pid, "First", 3000)
    assert "stair_rise_mismatch" in [i["code"] for i in _b(c, pid)["issues"]]


def test_offset_is_versioned_provenanced_and_flags_misalignment(proj):
    c, pid, _g, f = proj
    n = len(c.get(f"{P}/{pid}/versions").json())
    r = c.put(f"{P}/{pid}/floors/{f['id']}/offset", json={"x": 5000, "y": 0})
    assert r.status_code == 200 and r.json()["offset"]["source"] == "user_provided"
    assert len(c.get(f"{P}/{pid}/versions").json()) == n + 1
    b = _b(c, pid)
    assert b["floors"][1]["offset"]["x"] == 5000
    assert "floor_alignment_mismatch" in [i["code"] for i in b["issues"]]
    c.put(f"{P}/{pid}/floors/{f['id']}/offset", json={"x": 0, "y": 0})  # reset
    assert _b(c, pid)["floors"][1]["offset"]["source"] == "defaulted"
    assert c.put(f"{P}/{pid}/floors/nope/offset", json={"x": 1, "y": 1}).status_code == 404


def test_confirm_unpair_repair_and_restore(proj):
    c, pid, g, f = proj
    (p,) = _b(c, pid)["pairings"]
    ref = {k: p[k] for k in REF}
    assert c.put(f"{P}/{pid}/building/pairings", json=ref).json()["status"] == "confirmed"
    assert [x["status"] for x in _b(c, pid)["pairings"]] == ["confirmed"]
    saved = c.get(f"{P}/{pid}").json()["pairings"]
    assert [x["status"] for x in saved] == ["confirmed"]
    v_confirmed = c.get(f"{P}/{pid}").json()["version"]
    assert c.post(f"{P}/{pid}/building/pairings/unpair", json=ref).status_code == 200
    b = _b(c, pid)
    assert [x["status"] for x in b["pairings"]] == ["rejected"]
    assert "stair_unpaired" in [i["code"] for i in b["issues"]]
    assert c.put(f"{P}/{pid}/building/pairings", json=ref).status_code == 200  # re-pair
    assert _b(c, pid)["pairings"][0]["status"] == "confirmed"
    assert c.put(f"{P}/{pid}/building/pairings", json={**ref, "upper_stair": "x"}).status_code == 404
    swapped = {**ref, "upper_floor": g["id"], "upper_stair": ref["lower_stair"]}
    assert c.put(f"{P}/{pid}/building/pairings", json=swapped).status_code == 422
    # restoring the confirmed version brings its pairings back
    assert c.post(f"{P}/{pid}/versions/{v_confirmed}/restore").status_code == 201
    assert [x["status"] for x in _b(c, pid)["pairings"]] == ["confirmed"]
    # removing a floor drops its pairings
    c.delete(f"{P}/{pid}/floors/{f['id']}")
    assert _b(c, pid)["pairings"] == []


def test_auto_pairs_are_never_persisted(proj):
    c, pid, _g, _f = proj
    c.post(f"{P}/{pid}/building/pairings/unpair", json={k: _b(c, pid)["pairings"][0][k] for k in REF})
    assert [x["status"] for x in c.get(f"{P}/{pid}").json()["pairings"]] == ["rejected"]


def test_building_roles():
    owner, editor, viewer, stranger = (TestClient(app) for _ in range(4))
    pid = owner.post(P, json={"name": "B"}).json()["project_id"]
    _floor(owner, pid, "Ground", 0)
    f = _floor(owner, pid, "First", 3200)
    for c, role in ((editor, "editor"), (viewer, "viewer")):
        email = c.get("/api/v1/auth/me").json()["email"]
        owner.put(f"{P}/{pid}/access", json={"email": email, "role": role})
    ref = {k: _b(owner, pid)["pairings"][0][k] for k in REF}
    assert viewer.get(f"{P}/{pid}/building").status_code == 200
    assert stranger.get(f"{P}/{pid}/building").status_code == 404
    off = f"{P}/{pid}/floors/{f['id']}/offset"
    assert viewer.put(off, json={"x": 1, "y": 1}).status_code == 404
    assert viewer.put(f"{P}/{pid}/building/pairings", json=ref).status_code == 404
    assert stranger.put(off, json={"x": 1, "y": 1}).status_code == 404
    assert editor.put(off, json={"x": 1, "y": 1}).status_code == 200
    assert editor.post(f"{P}/{pid}/building/pairings/unpair", json=ref).status_code == 200
