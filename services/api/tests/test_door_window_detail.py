"""Doors and windows at medium detail: swing from arc symbols, frame + leaf/glass, lintel param."""

from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.geometry3d.extrude import build_opening_parts
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"


def _door(tmp_path, arc=None, window=False, extra=()):
    """One 200 mm wall along x (y 0..200), a 900 mm gap x 1000..1900 with a marker."""
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for y in (0, 200):
        for a, b in ((0, 1000), (1900, 3000)):
            msp.add_line((a, y), (b, y), dxfattribs={"layer": "A-WALL"})
    layer = "A-GLAZ" if window else "A-DOOR"
    msp.add_lwpolyline([(1000, 0), (1900, 0), (1900, 200), (1000, 200)], close=True,
                       dxfattribs={"layer": layer})
    for centre, start, end in ([arc] if arc else []) + list(extra):
        msp.add_arc(centre, 900, start, end, dxfattribs={"layer": "A-DOOR"})
    doc.saveas(tmp_path / "d.dxf")
    return read_dxf(tmp_path / "d.dxf", 2700, ceiling_height=2700)


def _open(p):
    (o,) = p.buildings[0].floors[0].openings
    return o


def test_swing_on_the_fixture_matches_the_drawn_arcs():
    # generator: D1 arc centre (3200,1000) 0-90 deg; D2 (6400,2000) 90-180; D3 (7500,200) 0-90
    p = read_dxf(INPUT / "fixture_openings.dxf", 3000, ceiling_height=3000)
    ops = {o.id: o for o in p.buildings[0].floors[0].openings}
    got = {k: (v.swing.hinge, v.swing.opens_toward) for k, v in ops.items() if v.swing}
    assert got == {"opening-003": ("start", "+y"), "opening-004": ("start", "+x"),
                   "opening-007": ("start", "-x")}
    assert all(v.swing is None for v in ops.values() if v.kind == "window")
    assert "door_swing_not_found" not in {i.code for i in p.issues}


def test_hinge_at_span_end_and_swing_to_negative_side(tmp_path):
    o = _open(_door(tmp_path, ((1900, 0), 180, 270)))
    assert (o.swing.hinge, o.swing.opens_toward) == ("end", "-y")


def test_missing_arc_leaves_swing_unset_with_an_issue(tmp_path):
    p = _door(tmp_path)
    assert _open(p).swing is None
    (i,) = [i for i in p.issues if i.code == "door_swing_not_found"]
    assert i.sources[0].layer == "A-DOOR"
    assert "door_swing_not_found" not in {x.code for x in _door(tmp_path, window=True).issues}


def test_two_arcs_on_one_door_are_ambiguous_not_guessed(tmp_path):
    p = _door(tmp_path, ((1000, 0), 0, 90), extra=[((1900, 0), 90, 180)])
    assert _open(p).swing is None
    assert "door_swing_ambiguous" in {i.code for i in p.issues}


def test_frame_and_panel_boxes_match_hand_calculation():
    p = read_dxf(INPUT / "fixture_openings.dxf", 3000, ceiling_height=3000)
    parts = build_opening_parts(p.buildings[0].floors[0])
    # door opening-003: x 7500..8400, wall y 0..200 (centre 100), head 2100, frame 50, leaf 40
    _, o, frame = parts["opening-003-frame"]
    assert frame.bounds.tolist() == [[7500, 0, 0], [8400, 200, 2100]]
    _, _, leaf = parts["opening-003-leaf"]
    assert leaf.bounds.tolist() == [[7550, 80, 0], [8350, 120, 2050]]
    # window opening-002: x 4400..5600, sill 900, height 1200, glass 24
    _, _, glass = parts["opening-002-glass"]
    assert glass.bounds.tolist() == [[4450, 88, 950], [5550, 112, 2050]]
    assert o.detail.panel_thickness.source == "defaulted"


def test_user_lintel_sizes_openings_but_default_lintel_does_not(tmp_path):
    # no building type here: CLI-style, so heights come from the Settings defaults
    base = _door(tmp_path, ((1000, 0), 0, 90))
    assert (_open(base).height.value, _open(base).height.source) == (2100.0, "defaulted")
    p = read_dxf(tmp_path / "d.dxf", 2700, ceiling_height=2700, building_type="commercial",
           params={"lintel_height": 2400})
    o = _open(p)
    assert (o.height.value, o.height.source) == (2400.0, "user_provided")
    w = read_dxf(tmp_path / "d.dxf", 2700, ceiling_height=2700, building_type="commercial")
    assert _open(w).height.source == "defaulted"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def test_editor_changes_lintel_and_openings_follow(client):
    owner = client
    pid = owner.post(P, json={"name": "H"}).json()["project_id"]
    up = owner.post("/api/v1/uploads", content=(INPUT / "fixture_openings.dxf").read_bytes()).json()["upload_id"]
    assert owner.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": "G", "elevation": 0}).status_code == 201
    editor = TestClient(app)
    email = editor.get("/api/v1/auth/me").json()["email"]
    assert owner.put(f"{P}/{pid}/access", json={"email": email, "role": "editor"}).status_code in (200, 201)
    r = editor.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"lintel_height": 2300})
    jobs.execute(r.json()["job_id"])
    assert editor.get(f"/api/v1/jobs/{r.json()['job_id']}").json()["status"] == "succeeded"
    gid = owner.get(f"{P}/{pid}").json()["floors"][0]["generation_id"]
    canon = owner.get(f"/api/v1/generations/{gid}/artifacts/canonical").json()
    ops = canon["buildings"][0]["floors"][0]["openings"]
    doors = [o for o in ops if o["kind"] == "door"]
    assert all(o["height"] == {"value": 2300.0, "unit": "mm", "source": "user_provided"} for o in doors)
    assert all(o["swing"] is not None for o in doors)  # swing survives regeneration
