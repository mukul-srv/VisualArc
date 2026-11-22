"""Columns and balconies/terraces (Phase 1/10)."""

import math
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import Project
from api.engine.conventions import ROLES, layer_roles, resolve
from api.engine.exporters.glb import build_meta, build_scene
from api.engine.geometry3d.extrude import build_balcony_railings, build_meshes
from api.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
COLUMNS = FIXTURES / "input" / "fixture_columns.dxf"
P = "/api/v1/projects"


def _read(path=COLUMNS, **kw):
    return read_dxf(path, 3000, ceiling_height=3000, building_type="residential", **kw)


def _floor(p):
    return p.buildings[0].floors[0]


def test_snapshot_matches_expected_fixture():
    expected = Project.model_validate_json(
        (FIXTURES / "expected" / "fixture_columns.canonical.json").read_text(encoding="utf-8"))
    assert _read() == expected


def test_columns_footprint_and_extrusion_match_hand_calculation():
    f = _floor(_read())
    rect, circle = f.columns
    assert rect.shape == "rect" and circle.shape == "circle"
    assert (rect.height.value, rect.height.source) == (3000.0, "user_provided")  # the ceiling param
    meshes = build_meshes(f)
    assert meshes[rect.id].volume == pytest.approx(300 * 300 * 3000)
    assert meshes[circle.id].volume == pytest.approx(math.pi * 200**2 * 3000, rel=2e-3)
    assert meshes[rect.id].bounds[:, 2].tolist() == [0, 3000]


def test_balcony_slab_and_railing_match_hand_calculation():
    p = _read()
    f = _floor(p)
    (b,) = f.balconies
    assert sum(math.dist(r.start, r.end) for r in b.railings) == pytest.approx(4000 + 1500 + 1500)
    assert (b.railing_height.value, b.railing_height.source) == (900.0, "defaulted")
    assert (b.thickness.value, b.thickness.source) == (200.0, "defaulted")
    slab = build_meshes(f)[b.id]
    assert slab.volume == pytest.approx(4000 * 1500 * 200)
    assert slab.bounds[:, 2].tolist() == [-200, 0]  # top at floor elevation
    rail = build_balcony_railings(f)[f"{b.id}-railing"][1]
    assert rail.bounds[:, 2].tolist() == [0, 900]
    meta = build_meta(p, build_scene(p))["elements"]
    assert meta["balcony-001"]["type"] == "balcony"
    assert meta["balcony-001-railing"]["type"] == "balcony_railing"
    assert {"col-001", "col-002"} <= set(meta)


def test_user_params_are_tagged_user_provided():
    p = _read(params={"railing_height": 1100, "slab_thickness": 150})
    b = _floor(p).balconies[0]
    assert (b.railing_height.value, b.railing_height.source) == (1100.0, "user_provided")
    assert (b.thickness.value, b.thickness.source) == (150.0, "user_provided")
    assert "railing_height_defaulted" not in {i.code for i in p.issues}


def test_no_building_type_means_no_railing_and_an_issue():
    p = read_dxf(COLUMNS, 3000, ceiling_height=3000)
    (b,) = _floor(p).balconies
    assert b.railing_height is None and b.railings == []
    assert "railing_height_missing" in {i.code for i in p.issues}


def _plan(tmp_path, cols=(), balc=()):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    outer = [(0, 0), (4400, 0), (4400, 3400), (0, 3400)]
    inner = [(200, 200), (4200, 200), (4200, 3200), (200, 3200)]
    for loop in (outer, inner):
        for i, a in enumerate(loop):
            msp.add_line(a, loop[(i + 1) % 4], dxfattribs={"layer": "A-WALL"})
    for pts, close in cols:
        msp.add_lwpolyline(pts, close=close, dxfattribs={"layer": "A-COLS"})
    for pts, close in balc:
        msp.add_lwpolyline(pts, close=close, dxfattribs={"layer": "A-BALC"})
    doc.saveas(tmp_path / "p.dxf")
    return _read(tmp_path / "p.dxf")


def _codes(p):
    return [i.code for i in p.issues]


def test_unsupported_columns_and_balconies_are_reported_not_dropped(tmp_path):
    rotated = [(1000, 1000), (1200, 1100), (1100, 1300), (900, 1200)]
    triangle = [(1000, 1000), (1300, 1000), (1000, 1300)]
    open_rect = [(1000, 1000), (1300, 1000), (1300, 1300), (1000, 1300)]
    p = _plan(
        tmp_path,
        cols=[(rotated, True), (triangle, True), (open_rect, False)],
        balc=[([(0, 0), (500, 0), (500, 500)], False)],
    )
    assert _codes(p).count("invalid_column") == 3 and not _floor(p).columns
    assert "invalid_balcony" in _codes(p) and not _floor(p).balconies


def test_balcony_overlapping_a_room_or_detached_is_warned_but_built(tmp_path):
    inside = [(1000, 1000), (2000, 1000), (2000, 2000), (1000, 2000)]
    far = [(8000, 8000), (9000, 8000), (9000, 9000), (8000, 9000)]
    p = _plan(tmp_path, balc=[(inside, True), (far, True)])
    assert {"balcony_overlaps_room", "balcony_detached"} <= set(_codes(p))
    assert len(_floor(p).balconies) == 2


def test_column_and_balcony_roles_in_conventions():
    assert {"column", "balcony"} <= set(ROLES)
    s = resolve("custom", {"STRUCT-COL": "column", "TERRACE": "balcony"})
    assert "STRUCT-COL" in s.column_layers and "TERRACE" in s.balcony_layers
    roles = {r["layer"]: r["role"] for r in layer_roles("aia", None, ["A-COLS", "A-BALC", "X"])}
    assert roles == {"A-COLS": "column", "A-BALC": "balcony", "X": None}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def test_editor_changes_railing_height_and_the_balcony_follows(client):
    owner = client
    pid = owner.post(P, json={"name": "H"}).json()["project_id"]
    up = owner.post("/api/v1/uploads", content=COLUMNS.read_bytes()).json()["upload_id"]
    body = {"upload_id": up, "floor_name": "G", "elevation": 0}
    assert owner.post(f"{P}/{pid}/floors", json=body).status_code == 201
    editor = TestClient(app)
    email = editor.get("/api/v1/auth/me").json()["email"]
    assert owner.put(f"{P}/{pid}/access", json={"email": email, "role": "editor"}).status_code in (200, 201)
    r = editor.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"railing_height": 1200, "ceiling_height": 2600})
    jobs.execute(r.json()["job_id"])
    assert editor.get(f"/api/v1/jobs/{r.json()['job_id']}").json()["status"] == "succeeded"
    gid = owner.get(f"{P}/{pid}").json()["floors"][0]["generation_id"]
    f = owner.get(f"/api/v1/generations/{gid}/artifacts/canonical").json()["buildings"][0]["floors"][0]
    assert f["balconies"][0]["railing_height"] == {"value": 1200.0, "unit": "mm", "source": "user_provided"}
    assert all(c["height"]["value"] == 2600.0 for c in f["columns"])


def test_columns_only_drawing_exports_without_crashing(tmp_path):
    # no walls: the ceiling height is not defaulted, so columns have no height
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    doc.modelspace().add_lwpolyline([(0, 0), (300, 0), (300, 300), (0, 300)], close=True,
                                    dxfattribs={"layer": "A-COLS"})
    doc.modelspace().add_circle((2000, 2000), 200, dxfattribs={"layer": "A-COLS"})
    doc.saveas(tmp_path / "c.dxf")
    p = read_dxf(tmp_path / "c.dxf", building_type="residential")
    f = _floor(p)
    assert len(f.columns) == 2 and all(c.height is None for c in f.columns)
    assert {"no_walls", "column_height_missing"} <= set(_codes(p))
    scene = build_scene(p)  # used to raise KeyError
    assert not scene.geometry  # nothing extruded, nothing silently invented
