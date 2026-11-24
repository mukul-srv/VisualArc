"""User edits (Section D): engine ops on a floor, then the job/API round trip with versions."""

from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from api import jobs
from api.db import ProjectVersionRow, session
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.edits import EditsRequest
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
H = {"wall_height": 3000, "ceiling_height": 3000}
P = "/api/v1/projects"


def _two_rooms(path: Path) -> Path:
    """8200 x 5200 box (200 mm walls, continuous faces) with a 200 mm partition at x = 4100: two 3800 x 4800 rooms."""
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for x0, y0, x1, y1 in ((0, 0, 8200, 5200), (200, 200, 8000, 5000)):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for i, a in enumerate(pts):
            msp.add_line(a, pts[(i + 1) % 4], dxfattribs={"layer": "A-WALL"})
    for x in (4000, 4200):
        msp.add_line((x, 200), (x, 5000), dxfattribs={"layer": "A-WALL"})
    doc.saveas(path)
    return path


@pytest.fixture
def two(tmp_path):
    return _two_rooms(tmp_path / "two.dxf")


def _read(path, ops=(), **kw):
    edits = EditsRequest.model_validate({"edits": list(ops)}).edits
    p = read_dxf(path, 3000, ceiling_height=3000, building_type="residential", edits=edits, **kw)
    return p, p.buildings[0].floors[0]


def _wall_ref(w):
    return {"start": w.centreline.start, "end": w.centreline.end, "thickness": w.thickness.value,
            "handles": [s.entity_handle for s in w.sources]}


def _partition(floor):
    return next(w for w in floor.walls if w.centreline.start[0] == 4100)


def _codes(p):
    return [i.code for i in p.issues]


def test_move_wall_rederives_rooms(two):
    _, f = _read(two)
    assert sorted(r.area.value for r in f.rooms) == [3800 * 4800] * 2
    ref = _wall_ref(_partition(f))
    p, f = _read(two, [{"op": "set_wall", "id": "e1", "target": ref, "start": [3100, 200], "end": [3100, 5000],
                        "thickness": 200}])
    assert sorted(r.area.value for r in f.rooms) == [2800 * 4800, 4800 * 4800]
    w = next(w for w in f.walls if w.centreline.start[0] == 3100)
    assert (w.thickness.source, w.sources[0].format, w.sources[0].entity_handle) == ("user_modified", "edit", "e1")
    assert "edit_target_missing" not in _codes(p)


def test_remove_wall_merges_rooms(two):
    _, f = _read(two)
    _, f = _read(two, [{"op": "remove_wall", "id": "e1", "target": _wall_ref(_partition(f))}])
    assert [r.area.value for r in f.rooms] == [7800 * 4800]


def test_add_wall_splits_a_room(two):
    _, f = _read(two, [{"op": "add_wall", "id": "e1", "start": [6000, 200], "end": [6000, 5000], "thickness": 200}])
    assert len(f.rooms) == 3
    assert sum(r.area.value for r in f.rooms) == pytest.approx(2 * 3800 * 4800 - 200 * 4800)  # the new wall's footprint


def test_add_door_to_a_wall_is_user_modified(two):
    _, f = _read(two)
    top = next(w for w in f.walls if w.centreline.start[1] == 100)
    _, f = _read(two, [{"op": "add_opening", "id": "e1", "wall": _wall_ref(top), "kind": "door",
                        "start": [1000, 100], "end": [1900, 100], "height": 2000}])
    (o,) = f.openings
    assert (o.kind, o.span.start, o.span.end) == ("door", (1000.0, 100.0), (1900.0, 100.0))
    assert (o.width.source, o.offset.source, o.height.value, o.height.source) == (
        "user_modified", "user_modified", 2000, "user_modified")
    assert o.sill_height.source == "defaulted" and o.sources[0].format == "edit"


def test_rename_room_is_user_modified(two):
    _, f = _read(two, [{"op": "rename_room", "id": "e1", "point": [1000, 1000], "name": " Kitchen "}])
    assert [(r.name, r.name_source) for r in f.rooms if r.name == "Kitchen"] == [("Kitchen", "user_modified")]


def test_stale_targets_warn_and_change_nothing(two):
    _, f = _read(two)
    stale = {**_wall_ref(_partition(f)), "handles": ["ZZ"]}
    ops = [
        {"op": "set_wall", "id": "e1", "target": stale, "start": [3100, 200], "end": [3100, 5000], "thickness": 200},
        {"op": "remove_wall", "id": "e2", "target": stale},
        {"op": "remove_opening", "id": "e3", "target": {"kind": "door", "start": [0, 0], "end": [1000, 0], "handles": ["ZZ"]}},
        {"op": "rename_room", "id": "e4", "point": [-5000, -5000], "name": "Nowhere"},
    ]
    p, f2 = _read(two, ops)
    assert _codes(p).count("edit_target_missing") == 4
    assert [r.area.value for r in f2.rooms] == [r.area.value for r in f.rooms]
    assert len(f2.walls) == len(f.walls)
    assert all(i.sources[0].format == "edit" for i in p.issues if i.code == "edit_target_missing")


def test_non_orthogonal_and_duplicate_edits_are_rejected():
    bad = {"op": "add_wall", "id": "e1", "start": [0, 0], "end": [1000, 500], "thickness": 200}
    with pytest.raises(ValidationError, match="orthogonal"):
        EditsRequest.model_validate({"edits": [bad]})
    ok = {**bad, "end": [1000, 0]}
    with pytest.raises(ValidationError, match="unique"):
        EditsRequest.model_validate({"edits": [ok, ok]})


# --- openings of a real drawing -------------------------------------------------------------------------

OPENINGS = INPUT / "fixture_openings.dxf"


def _ref(o):
    return {"kind": o.kind, "start": o.span.start, "end": o.span.end,
            "handles": [s.entity_handle for s in o.sources]}


def _window(f):  # a window on a horizontal wall, taken from the model as the editor would
    return next(o for o in f.openings if o.kind == "window" and o.span.start[1] == o.span.end[1])


def test_move_opening_and_remove_opening_close_the_old_gap():
    _, f0 = _read(OPENINGS)
    w = _window(f0)
    a, b = w.span.start[0] + 200, w.span.end[0] - 200
    p, f = _read(OPENINGS, [{"op": "set_opening", "id": "e1", "target": _ref(w), "kind": "window",
                             "start": [a, w.span.start[1]], "end": [b, w.span.start[1]], "height": 900, "sill_height": 1000}])
    o = next(o for o in f.openings if o.sources[0].entity_handle == "e1")
    assert (o.span.start[0], o.span.end[0], o.width.value) == (a, b, b - a)
    assert (o.height.source, o.sill_height.value, o.width.source) == ("user_modified", 1000, "user_modified")
    assert len(f.openings) == len(f0.openings)
    assert not {"unmarked_wall_gap", "unmarked_gap_bridged"} & set(_codes(p))
    p, f = _read(OPENINGS, [{"op": "remove_opening", "id": "e1", "target": _ref(w)}])
    assert len(f.openings) == len(f0.openings) - 1
    assert not {"unmarked_wall_gap", "unmarked_gap_bridged"} & set(_codes(p))
    assert len(f.walls) == len(f0.walls)


def test_remove_wall_removes_its_openings_with_an_issue():
    _, f0 = _read(OPENINGS)
    host = next(w for w in f0.walls if w.id == _window(f0).wall_id)
    on_host = [o for o in f0.openings if o.wall_id == host.id]
    p, f = _read(OPENINGS, [{"op": "remove_wall", "id": "e1", "target": _wall_ref(host)}])
    assert len(f.openings) == len(f0.openings) - len(on_host)
    removed = [i for i in p.issues if i.code == "edit_opening_removed"]
    assert len(removed) == len(on_host) and "removed wall" in removed[0].message and removed[0].sources[0].format == "edit"


def test_bad_opening_edit_is_blocking():
    _, f0 = _read(OPENINGS)
    w = _window(f0)
    p, _ = _read(OPENINGS, [{"op": "set_opening", "id": "e1", "target": _ref(w), "kind": "window",
                             "start": w.span.start, "end": w.span.end, "height": 3500}])
    assert any(i.code == "opening_exceeds_wall_height" and i.severity == "blocking" for i in p.issues)


# --- API: job, versions, parameters ------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def _project(c, tmp_path):
    pid = c.post(P, json={"name": "E"}).json()["project_id"]
    up = c.post("/api/v1/uploads", content=_two_rooms(tmp_path / "two.dxf").read_bytes()).json()["upload_id"]
    r = c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": "G", "elevation": 0, **H})
    assert r.status_code == 201, r.text
    return pid, r.json()["floor"]["id"]


def _job(c, r):
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    jobs.execute(jid)
    return c.get(f"/api/v1/jobs/{jid}").json()


def _edit(c, pid, fid, edits):
    return _job(c, c.put(f"/api/v1/jobs/projects/{pid}/floors/{fid}/edits", json={"edits": edits}))


def _versions(pid):
    with session() as db:
        return db.scalar(select(func.count()).select_from(ProjectVersionRow).where(ProjectVersionRow.project_id == pid))


def _plan(c, pid, fid):
    return c.get(f"{P}/{pid}/floors/{fid}/plan").json()


def _move(c, pid, fid):
    w = next(w for w in _plan(c, pid, fid)["model"]["walls"] if w["start"][0] == 4100)
    ref = {"start": w["start"], "end": w["end"], "thickness": w["thickness"], "handles": w["handles"]}
    return [{"op": "set_wall", "id": "e1", "target": ref, "start": [3100, 200], "end": [3100, 5000], "thickness": 200}]


def _areas(c, pid, fid):
    return sorted(r["area"] for r in _plan(c, pid, fid)["model"]["rooms"])


def test_edit_job_replays_one_floor_and_makes_one_version(client, tmp_path):
    pid, fid = _project(client, tmp_path)
    before = _versions(pid)
    ov = _plan(client, pid, fid)
    assert _areas(client, pid, fid) == [3800 * 4800] * 2
    assert ov["edits"] == [] and all(w["handles"] and w["provenance"] for w in ov["model"]["walls"])
    assert all(len(r["label_point"]) == 2 for r in ov["model"]["rooms"])
    j = _edit(client, pid, fid, _move(client, pid, fid))
    assert j["status"] == "succeeded", j
    assert _versions(pid) == before + 1
    assert _areas(client, pid, fid) == [2800 * 4800, 4800 * 4800]
    ov = _plan(client, pid, fid)
    assert ov["edits"][0]["id"] == "e1"
    moved = next(w for w in ov["model"]["walls"] if w["start"][0] == 3100)
    assert (moved["provenance"], moved["handles"]) == ("user_modified", ["e1", "e1"])


def test_edits_survive_parameter_change_and_restore_drops_them(client, tmp_path):
    pid, fid = _project(client, tmp_path)
    original = client.get(f"{P}/{pid}").json()["version"]
    assert _edit(client, pid, fid, _move(client, pid, fid))["status"] == "succeeded"
    edited = client.get(f"{P}/{pid}").json()["version"]
    j = _job(client, client.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"wall_height": 3200, "ceiling_height": 3200}))
    assert j["status"] == "succeeded", j
    assert _areas(client, pid, fid) == [2800 * 4800, 4800 * 4800]  # the edit is still applied
    assert client.get(f"{P}/{pid}?version={edited}").json()["floors"][0]["edits"][0]["id"] == "e1"
    assert "edits" not in client.get(f"{P}/{pid}?version={original}").json()["floors"][0]
    assert client.post(f"{P}/{pid}/versions/{original}/restore").status_code == 201
    assert _plan(client, pid, fid)["edits"] == []
    assert _areas(client, pid, fid) == [3800 * 4800] * 2


def test_blocking_edit_saves_nothing(client, tmp_path):
    pid, fid = _project(client, tmp_path)
    before = _versions(pid)
    top = next(w for w in _plan(client, pid, fid)["model"]["walls"] if w["start"][1] == 100)
    ref = {"start": top["start"], "end": top["end"], "thickness": top["thickness"], "handles": top["handles"]}
    op = {"op": "add_opening", "id": "e1", "wall": ref, "kind": "door", "start": [1000, 100], "end": [1900, 100],
          "height": 3500}
    j = _edit(client, pid, fid, [op])
    assert j["status"] == "failed"
    assert "opening_exceeds_wall_height" in {i["code"] for i in j["result"]["issues"]}
    assert _versions(pid) == before and _plan(client, pid, fid)["edits"] == []


def test_edits_api_validation_and_access(client, tmp_path):
    pid, fid = _project(client, tmp_path)
    url = f"/api/v1/jobs/projects/{pid}/floors/{fid}/edits"
    bad = {"op": "add_wall", "id": "e1", "start": [0, 0], "end": [1000, 500], "thickness": 200}
    assert client.put(url, json={"edits": [bad]}).status_code == 422
    assert client.put(f"/api/v1/jobs/projects/{pid}/floors/floor-9/edits", json={"edits": []}).status_code == 404
    assert TestClient(app).put(url, json={"edits": []}).status_code == 404  # another account


def test_overlay_reports_edited_openings_with_their_details(client, tmp_path):
    pid, fid = _project(client, tmp_path)
    top = next(w for w in _plan(client, pid, fid)["model"]["walls"] if w["start"][1] == 100)
    ref = {k: top[k] for k in ("start", "end", "thickness", "handles")}
    op = {"op": "add_opening", "id": "e1", "wall": ref, "kind": "window", "start": [1000, 100], "end": [2000, 100],
          "height": 1100, "sill_height": 900}
    assert _edit(client, pid, fid, [op])["status"] == "succeeded"
    (o,) = _plan(client, pid, fid)["model"]["openings"]
    assert (o["width"], o["height"], o["sill"], o["provenance"], o["handles"][0]) == (1000, 1100, 900, "user_modified", "e1")
    assert o["wall_id"].startswith("wall-")
