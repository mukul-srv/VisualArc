"""Roofs: flat, gable and hip over the building outline (Phase 1/12)."""

import math
from pathlib import Path

import ezdxf
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import Project
from api.engine.conventions import ROLES, layer_roles, resolve
from api.engine.exporters.glb import build_meta, build_scene
from api.engine.geometry3d.extrude import build_meshes, build_roof
from api.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
ROOFS = FIXTURES / "input" / "fixture_roofs.dxf"
P = "/api/v1/projects"
TAN30 = math.tan(math.radians(30))
H_GABLE = 2500 * TAN30  # fixture: 7000 x 5000 eaves, half-span 2500


def _read(path=ROOFS, **kw):
    kw.setdefault("building_type", "residential")
    return read_dxf(path, 3000, ceiling_height=3000, **kw)


def _floor(p):
    return p.buildings[0].floors[0]


def _codes(p):
    return [i.code for i in p.issues]


def _walls_only(tmp_path, name="w", outer=(6400, 4400)):
    """The fixture's building without the roof-plan layer (or with another size)."""
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    w, h = outer
    for loop in ([(0, 0), (w, 0), (w, h), (0, h)], [(200, 200), (w - 200, 200), (w - 200, h - 200), (200, h - 200)]):
        for i, a in enumerate(loop):
            msp.add_line(a, loop[(i + 1) % 4], dxfattribs={"layer": "A-WALL"})
    doc.saveas(tmp_path / f"{name}.dxf")
    return tmp_path / f"{name}.dxf"


def test_snapshot_matches_expected_fixture():
    expected = Project.model_validate_json(
        (FIXTURES / "expected" / "fixture_roofs.canonical.json").read_text(encoding="utf-8"))
    assert _read() == expected


def test_default_gable_ridge_height_and_volume_match_hand_calculation():
    p = _read()
    (r,) = _floor(p).roofs
    assert (r.kind, r.requested, r.outline_source, r.ridge_axis) == ("gable", "gable", "roof_layer", "x")
    assert (r.type_param.value, r.type_param.source) == ("gable", "defaulted")
    assert (r.pitch.value, r.pitch.source) == (30.0, "defaulted")
    assert r.base_elevation.value == 3000.0  # floor 0 + wall height
    assert r.ridge_height.value == pytest.approx(H_GABLE)  # half-span * tan(pitch)
    assert (r.overhang.value, r.overhang.source) == (0.0, "source_extracted")  # a drawn outline is the edge
    assert {"roof_type_defaulted"} <= set(_codes(p))
    mesh = build_meshes(_floor(p))[r.id]
    assert mesh.is_watertight and mesh.volume == pytest.approx(0.5 * 5000 * H_GABLE * 7000)
    np.testing.assert_allclose(mesh.bounds, [[-300, -300, 3000], [6700, 4700, 3000 + H_GABLE]])


def test_roof_from_the_walls_adds_the_eave_overhang(tmp_path):
    p = _read(_walls_only(tmp_path))
    (r,) = _floor(p).roofs
    assert r.outline_source == "walls" and r.sources == []
    assert (r.overhang.value, r.overhang.source) == (300.0, "defaulted")
    assert r.ridge_height.value == pytest.approx(H_GABLE)  # (4400 + 2 x 300) / 2 x tan 30
    mesh = build_meshes(_floor(p))[r.id]
    np.testing.assert_allclose(mesh.bounds, [[-300, -300, 3000], [6700, 4700, 3000 + H_GABLE]])


def test_hip_with_user_type_and_pitch(tmp_path):
    p = _read(params={"roof_type": "hip", "roof_pitch": 20})
    (r,) = _floor(p).roofs
    h = 2500 * math.tan(math.radians(20))
    assert (r.kind, r.type_param.source, r.pitch.source) == ("hip", "user_provided", "user_provided")
    assert r.ridge_height.value == pytest.approx(h)
    assert not {"roof_type_defaulted", "roof_pitch_defaulted"} & set(_codes(p))
    mesh = build_meshes(_floor(p))[r.id]
    L, W = 7000, 5000
    assert mesh.is_watertight and mesh.volume == pytest.approx(W * h / 6 * (3 * L - W))  # hip volume
    # the ridge is the long side minus the short side, centred on y = 2200
    top = mesh.vertices[mesh.vertices[:, 2] > 3000 + h - 1e-6]
    assert sorted(set(top[:, 0].round(6))) == [2200.0, 4200.0] and set(top[:, 1].round(6)) == {2200.0}


def test_hip_over_a_square_is_a_pyramid(tmp_path):
    p = _read(_walls_only(tmp_path, outer=(4400, 4400)), params={"roof_type": "hip"})
    (r,) = _floor(p).roofs
    mesh = build_meshes(_floor(p))[r.id]
    side, h = 5000, 2500 * TAN30
    assert r.kind == "hip" and mesh.is_watertight and mesh.volume == pytest.approx(side * side * h / 3)


def test_commercial_default_is_a_flat_slab():
    p = _read(building_type="commercial", path=ROOFS)
    (r,) = _floor(p).roofs
    assert (r.kind, r.type_param.source) == ("flat", "defaulted") and r.pitch is None
    assert (r.thickness.value, r.thickness.source) == (200.0, "defaulted")
    mesh = build_meshes(_floor(p))[r.id]
    assert mesh.volume == pytest.approx(7000 * 5000 * 200)
    assert mesh.bounds[:, 2].tolist() == [3000, 3200]


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"params": {"roof_type": "hip", "roof_pitch": 0}}, "roof_pitch_invalid"),
        ({"building_type": None, "params": {"roof_type": "gable"}}, "roof_pitch_unknown"),
    ],
)
def test_bad_or_missing_pitch_falls_back_to_a_reported_flat_roof(kw, code):
    p = _read(**kw)
    (r,) = _floor(p).roofs
    assert r.kind == "flat" and r.requested in ("hip", "gable")  # never silently the requested type
    assert code in _codes(p)


def test_unsupported_outlines_fall_back_to_flat_with_an_issue(tmp_path):
    b = FIXTURES / "input" / "fixture_b.dxf"  # L-shaped building
    p = _read(b)
    (r,) = _floor(p).roofs
    assert (r.kind, r.requested) == ("flat", "gable") and "roof_shape_unsupported" in _codes(p)
    sq = _read(_walls_only(tmp_path, outer=(4400, 4400)))  # square gable: ridge direction unknown
    assert _floor(sq).roofs[0].kind == "flat" and "roof_ridge_ambiguous" in _codes(sq)


def test_no_building_type_and_no_roof_type_builds_nothing_but_says_so():
    p = read_dxf(ROOFS, 3000, ceiling_height=3000)
    assert not _floor(p).roofs and "roof_type_unknown" in _codes(p)


def test_missing_wall_height_records_the_roof_without_a_base(tmp_path):
    p = read_dxf(ROOFS, params={"roof_type": "gable", "roof_pitch": 30})  # no heights, no preset
    (r,) = _floor(p).roofs
    assert r.base_elevation is None and "roof_base_unknown" in _codes(p)
    assert build_roof(r) is None  # nothing invented


def test_no_walls_means_no_roof_and_a_reported_outline(tmp_path):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    doc.modelspace().add_lwpolyline([(0, 0), (5000, 0), (5000, 4000), (0, 4000)], close=True,
                                    dxfattribs={"layer": "A-ROOF"})
    doc.saveas(tmp_path / "r.dxf")
    p = read_dxf(tmp_path / "r.dxf", building_type="residential")
    assert not _floor(p).roofs and {"no_walls", "roof_without_walls"} <= set(_codes(p))
    build_scene(p)  # nothing to extrude, and no crash


def test_roof_not_on_the_top_floor_is_reported():
    p = read_dxf(ROOFS, 3000, ceiling_height=3000, building_type="residential", roof=False)
    assert not _floor(p).roofs and "roof_not_top_floor" in _codes(p)


def test_roof_nodes_export_in_the_glb():
    for kw in ({}, {"params": {"roof_type": "hip"}}, {"building_type": "commercial"}):
        p = _read(**kw)
        el = build_meta(p, build_scene(p))["elements"]
        assert el["roof-001"]["type"] == "roof" and el["roof-001"]["watertight"]


def test_roof_role_in_conventions():
    assert "roof" in ROLES
    assert "OVERHEAD" in resolve("custom", {"OVERHEAD": "roof"}).roof_layers
    assert {r["layer"]: r["role"] for r in layer_roles("aia", None, ["A-ROOF"])} == {"A-ROOF": "roof"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def _canon(c, gid):
    return c.get(f"/api/v1/generations/{gid}/artifacts/canonical").json()["buildings"][0]["floors"][0]


def _add(c, pid, name, elevation):
    up = c.post("/api/v1/uploads", content=ROOFS.read_bytes()).json()["upload_id"]
    r = c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": name, "elevation": elevation,
                                          "wall_height": 3000, "ceiling_height": 3000})
    assert r.status_code == 201, r.text


def _roofs(c, pid):
    return {f["name"]: len(_canon(c, f["generation_id"])["roofs"]) for f in c.get(f"{P}/{pid}").json()["floors"]}


def test_only_the_top_floor_has_a_roof_through_add_remove_and_regenerate(client):
    c = client
    pid = c.post(P, json={"name": "H"}).json()["project_id"]
    _add(c, pid, "Ground", 0)
    assert _roofs(c, pid) == {"Ground": 1}
    _add(c, pid, "First", 3200)  # the new top floor takes the roof, the old one gives it up
    assert _roofs(c, pid) == {"Ground": 0, "First": 1}
    _add(c, pid, "Cellar", -3200)  # a floor below changes nothing
    assert _roofs(c, pid) == {"Ground": 0, "First": 1, "Cellar": 0}
    # an editor changes the roof type through the job route: only the top floor's roof follows
    editor = TestClient(app)
    email = editor.get("/api/v1/auth/me").json()["email"]
    assert c.put(f"{P}/{pid}/access", json={"email": email, "role": "editor"}).status_code in (200, 201)
    r = editor.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"roof_type": "hip", "roof_pitch": 25})
    jobs.execute(r.json()["job_id"])
    assert editor.get(f"/api/v1/jobs/{r.json()['job_id']}").json()["status"] == "succeeded"
    floors = {f["name"]: _canon(c, f["generation_id"]) for f in c.get(f"{P}/{pid}").json()["floors"]}
    assert {n: len(f["roofs"]) for n, f in floors.items()} == {"Ground": 0, "First": 1, "Cellar": 0}
    roof = floors["First"]["roofs"][0]
    assert roof["kind"] == "hip" and roof["pitch"] == {"value": 25.0, "unit": "deg", "source": "user_provided"}
    # removing the top floor moves the roof down to the new highest floor
    fid = next(f["id"] for f in c.get(f"{P}/{pid}").json()["floors"] if f["name"] == "First")
    assert c.delete(f"{P}/{pid}/floors/{fid}").status_code == 204
    assert _roofs(c, pid) == {"Ground": 1, "Cellar": 0}


@pytest.mark.parametrize("kind", ["gable", "hip"])
def test_ridge_along_y_on_a_tall_building(tmp_path, kind):
    # 4400 x 6400 outer: the long side is y, so the ridge runs along y; eaves 5000 x 7000
    p = _read(_walls_only(tmp_path, outer=(4400, 6400)), params={"roof_type": kind})
    (r,) = _floor(p).roofs
    assert r.kind == kind and r.ridge_axis == "y"
    mesh = build_meshes(_floor(p))[r.id]
    h, W, L = H_GABLE, 5000, 7000
    expected = 0.5 * W * h * L if kind == "gable" else W * h / 6 * (3 * L - W)
    assert mesh.is_watertight and mesh.volume == pytest.approx(expected)
    top = mesh.vertices[mesh.vertices[:, 2] > 3000 + h - 1e-6]
    assert set(top[:, 0].round(6)) == {2200.0}  # the ridge sits on x = 2200
    inset = 0 if kind == "gable" else W / 2
    assert sorted(set(top[:, 1].round(6))) == [-300.0 + inset, 6700.0 - inset]


def test_removing_the_top_floor_reports_a_roof_that_cannot_move(client):
    from api.db import ProjectRow, session

    c = client
    pid = c.post(P, json={"name": "H"}).json()["project_id"]
    _add(c, pid, "Ground", 0)
    _add(c, pid, "First", 3200)
    with session() as db, db.begin():  # make the lower floor a legacy one (no stored request)
        row = db.get(ProjectRow, pid)
        row.data = {**row.data, "floors": [
            {k: v for k, v in f.items() if k != "request"} if f["name"] == "Ground" else f
            for f in row.data["floors"]]}
    fid = next(f["id"] for f in c.get(f"{P}/{pid}").json()["floors"] if f["name"] == "First")
    r = c.delete(f"{P}/{pid}/floors/{fid}")
    assert r.status_code == 200 and r.json()["issues"][0]["code"] == "roof_on_lower_floor"
    assert [f["name"] for f in c.get(f"{P}/{pid}").json()["floors"]] == ["Ground"]  # removed regardless
    # a normal removal stays a plain 204
    pid2 = c.post(P, json={"name": "H2"}).json()["project_id"]
    _add(c, pid2, "Ground", 0)
    _add(c, pid2, "First", 3200)
    fid2 = next(f["id"] for f in c.get(f"{P}/{pid2}").json()["floors"] if f["name"] == "First")
    assert c.delete(f"{P}/{pid2}/floors/{fid2}").status_code == 204
