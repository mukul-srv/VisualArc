"""Stairs and ramps, single floor (Phase 1/11)."""

from dataclasses import replace
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import Project
from api.engine.conventions import ROLES, layer_roles, resolve
from api.engine.exporters.glb import build_meta, build_scene
from api.engine.geometry3d.extrude import build_meshes
from api.engine.settings import DEFAULTS
from api.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
STAIRS = FIXTURES / "input" / "fixture_stairs.dxf"
P = "/api/v1/projects"
PARAMS = {"stair_rise": 160, "stair_run": 250}


NO_INFER = replace(DEFAULTS, infer_floor_boundary=False)  # these stair tests assume a floor with no slab


def _read(path=STAIRS, params=PARAMS, **kw):
    return read_dxf(path, 3000, ceiling_height=3000, building_type="residential", params=params, **kw)


def _floor(p):
    return p.buildings[0].floors[0]


def _codes(p):
    return [i.code for i in p.issues]


def test_snapshot_matches_expected_fixture():
    expected = Project.model_validate_json(
        (FIXTURES / "expected" / "fixture_stairs.canonical.json").read_text(encoding="utf-8"))
    assert _read() == expected


def test_stair_step_count_riser_and_tread_match_hand_calculation():
    # total rise 3000 + 200 = 3200; rise 160 -> 20 risers; 4750 mm / 19 treads = 250 mm
    (s,) = _floor(_read()).stairs
    assert (s.total_rise.value, s.total_rise.source) == (3200.0, "inferred")
    assert s.riser_count == 20 and s.direction == "+x"
    assert (s.riser_height.value, s.riser_height.source) == (160.0, "inferred")
    assert s.tread_depth.value == pytest.approx(250.0)
    assert (s.rise_param.source, s.run_param.source) == ("user_provided", "user_provided")
    mesh = build_meshes(_floor(_read()))[s.id]
    assert mesh.volume == pytest.approx(250 * 1000 * 160 * (19 * 20 / 2))  # sum of blocks k = 1..19
    # starts at the finished floor (200 mm slab); the top riser is the floor above
    assert mesh.bounds.tolist() == [[450, 500, 200], [5200, 1500, 200 + 19 * 160]]
    assert "stair_run_mismatch" not in _codes(_read())


def test_ramp_slope_and_slab_match_hand_calculation():
    p = _read()
    (r,) = _floor(p).ramps
    assert r.slope == pytest.approx(3200 / 4750) and r.rise.value == 3200.0
    assert (r.thickness.value, r.thickness.source) == (200.0, "defaulted")
    mesh = build_meshes(_floor(p))[r.id]
    assert mesh.is_watertight and mesh.volume == pytest.approx(1000 * 4750 * 200)
    assert mesh.bounds[:, 2].tolist() == [0, 3400]  # rises 3200 from the finished floor (200); slab 200 thick
    steep = [i for i in p.issues if i.code == "ramp_slope_steep"]
    assert len(steep) == 1 and "1:1.5" in steep[0].message
    meta = build_meta(p, build_scene(p))["elements"]
    assert meta["stair-001"]["type"] == "stair" and meta["ramp-001"]["type"] == "ramp"


def _plan(tmp_path, *, stair=True, arrows=((450, 1000, 5200, 1000),), extra=(), walls=True, name="p"):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    if walls:
        for loop in ([(0, 0), (6400, 0), (6400, 4400), (0, 4400)], [(200, 200), (6200, 200), (6200, 4200), (200, 4200)]):
            for i, a in enumerate(loop):
                msp.add_line(a, loop[(i + 1) % 4], dxfattribs={"layer": "A-WALL"})
    if stair:
        msp.add_lwpolyline([(450, 500), (5200, 500), (5200, 1500), (450, 1500)], close=True,
                           dxfattribs={"layer": "A-FLOR-STRS"})
    for x0, y0, x1, y1 in arrows:
        msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": "A-FLOR-STRS"})
    for layer, pts, close in extra:
        msp.add_lwpolyline(pts, close=close, dxfattribs={"layer": layer})
    doc.saveas(tmp_path / f"{name}.dxf")
    return tmp_path / f"{name}.dxf"


@pytest.mark.parametrize(
    ("arrow", "direction"),
    [((5200, 1000, 450, 1000), "-x"), ((450, 1000, 5200, 1000), "+x")],
)
def test_arrow_direction_flips_the_flight(tmp_path, arrow, direction):
    p = _read(_plan(tmp_path, arrows=[arrow]), settings=NO_INFER)
    (s,) = _floor(p).stairs
    assert s.direction == direction
    first = build_meshes(_floor(p))[s.id].bounds
    assert first[:, 2].tolist() == [0, 19 * 160]  # same steps, mirrored along x (no floor slab here)


def test_vertical_arrow_gives_y_direction_and_uses_the_other_extent(tmp_path):
    p = _read(_plan(tmp_path, arrows=[(1000, 500, 1000, 1500)]), params={"stair_rise": 160, "stair_run": 250})
    (s,) = _floor(p).stairs
    assert s.direction == "+y" and s.riser_count == 20
    assert s.tread_depth.value == pytest.approx(1000 / 19)  # 1000 mm drawn / 19 treads
    assert "stair_run_mismatch" in _codes(p)  # 52.6 mm treads are nothing like 250


@pytest.mark.parametrize(
    ("arrows", "code"),
    [
        ([], "stair_direction_missing"),
        ([(450, 800, 5200, 800), (450, 1200, 5200, 1200)], "stair_direction_ambiguous"),
        ([(450, 500, 1000, 1500)], "stair_direction_unusable"),
    ],
)
def test_unknown_direction_is_reported_and_nothing_is_built(tmp_path, arrows, code):
    p = _read(_plan(tmp_path, arrows=arrows))
    (s,) = _floor(p).stairs
    assert s.direction is None and s.riser_count is None
    assert code in _codes(p)
    assert s.id not in build_meshes(_floor(p))
    build_scene(p)  # a flight without steps must not break the export


def test_orphan_arrow_and_invalid_outline_are_reported(tmp_path):
    p = _read(_plan(tmp_path, stair=False, arrows=[(450, 1000, 5200, 1000)],
                    extra=[("A-FLOR-STRS", [(0, 0), (500, 0), (500, 500)], True),
                           ("A-FLOR-RAMP", [(0, 0), (500, 0), (500, 500), (0, 500)], False)]))
    assert not _floor(p).stairs and not _floor(p).ramps
    assert {"stair_arrow_orphan", "invalid_stair", "invalid_ramp"} <= set(_codes(p))


def test_incompatible_run_and_too_low_a_rise_are_warned(tmp_path):
    path = _plan(tmp_path)
    p = _read(path, params={"stair_rise": 160, "stair_run": 400})
    (s,) = _floor(p).stairs
    assert s.riser_count == 20 and "stair_run_mismatch" in _codes(p)  # built as drawn, 250 != 400
    low = read_dxf(path, 3000, ceiling_height=100, building_type="residential", params={"slab_thickness": 100})
    assert "stair_too_low" in _codes(low) and _floor(low).stairs[0].riser_count is None


def test_no_walls_and_missing_heights_do_not_crash_or_guess(tmp_path):
    # no walls: the ceiling height is not defaulted, so the total rise is unknown
    path = _plan(tmp_path, walls=False)
    p = read_dxf(path, building_type="residential")
    s = _floor(p).stairs[0]
    assert s.total_rise is None and s.riser_count is None
    assert {"no_walls", "stair_rise_unknown"} <= set(_codes(p))
    build_scene(p)
    # no building type and no slab thickness given: no steps, and the reason is stated
    q = read_dxf(_plan(tmp_path, name="q"), 3000, ceiling_height=3000)
    assert _floor(q).stairs[0].riser_count is None
    (i,) = [i for i in q.issues if i.code == "stair_rise_unknown"]
    assert "slab thickness" in i.message


def test_stair_and_ramp_roles_in_conventions():
    assert {"stair", "ramp"} <= set(ROLES)
    s = resolve("custom", {"STAIRS": "stair", "RAMPS": "ramp"})
    assert "STAIRS" in s.stair_layers and "RAMPS" in s.ramp_layers
    roles = {r["layer"]: r["role"] for r in layer_roles("aia", None, ["A-FLOR-STRS", "A-FLOR-RAMP"])}
    assert roles == {"A-FLOR-STRS": "stair", "A-FLOR-RAMP": "ramp"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)
    return TestClient(app)


def test_editor_changes_stair_rise_and_the_steps_follow(client):
    owner = client
    pid = owner.post(P, json={"name": "H"}).json()["project_id"]
    up = owner.post("/api/v1/uploads", content=STAIRS.read_bytes()).json()["upload_id"]
    body = {"upload_id": up, "floor_name": "G", "elevation": 0, "ceiling_height": 3000}
    assert owner.post(f"{P}/{pid}/floors", json=body).status_code == 201
    editor = TestClient(app)
    email = editor.get("/api/v1/auth/me").json()["email"]
    assert owner.put(f"{P}/{pid}/access", json={"email": email, "role": "editor"}).status_code in (200, 201)
    r = editor.post(f"/api/v1/jobs/projects/{pid}/parameters", json={"stair_rise": 200})
    jobs.execute(r.json()["job_id"])
    assert editor.get(f"/api/v1/jobs/{r.json()['job_id']}").json()["status"] == "succeeded"
    gid = owner.get(f"{P}/{pid}").json()["floors"][0]["generation_id"]
    f = owner.get(f"/api/v1/generations/{gid}/artifacts/canonical").json()["buildings"][0]["floors"][0]
    s = f["stairs"][0]
    assert s["riser_count"] == 16 and s["rise_param"] == {"value": 200.0, "unit": "mm", "source": "user_provided"}
    assert s["riser_height"]["value"] == 200.0  # 3200 / 16


def test_missing_rise_parameter_is_reported_not_silent(tmp_path):
    # total rise is known (ceiling + slab given) but there is no building type or stair rise
    p = read_dxf(_plan(tmp_path), 3000, ceiling_height=3000, params={"slab_thickness": 200})
    (s,) = _floor(p).stairs
    assert s.total_rise.value == 3200.0 and s.riser_count is None and s.rise_param is None
    assert "stair_rise_param_missing" in _codes(p)


def test_default_slab_is_reported_once_for_stairs_and_balconies_without_floor_boundary(tmp_path):
    balcony = [("A-BALC", [(1000, -1500), (5000, -1500), (5000, 0), (1000, 0)], True)]
    for extra in ([], balcony):  # stairs only, then stairs + a balcony; no A-FLOR in either
        p = _read(_plan(tmp_path, extra=extra), params=None)
        assert _codes(p).count("slab_thickness_defaulted") == 1
    # user-given thickness: nothing to report
    assert "slab_thickness_defaulted" not in _codes(_read(_plan(tmp_path), params={"slab_thickness": 200}))


def test_arrow_inside_two_overlapping_outlines_is_ambiguous(tmp_path):
    overlap = [("A-FLOR-STRS", [(450, 800), (5200, 800), (5200, 1800), (450, 1800)], True)]
    p = _read(_plan(tmp_path, extra=overlap))  # the arrow at y=1000 lies in both outlines
    assert len(_floor(p).stairs) == 2 and all(s.direction is None for s in _floor(p).stairs)
    assert _codes(p).count("stair_direction_ambiguous") == 2


def test_stairs_rise_to_the_next_finished_floor_which_follows_the_ceiling(tmp_path):
    # hand case, wall 3600 / ceiling 3000 / slab 200, floor at elevation 0:
    #   finished floor 200; ceiling plane 200 + 3000 = 3200; the next slab's underside is that plane
    #   (3200) and the next finished floor 3200 + 200 = 3400. The stair rises 3400 - 200 = 3200 (20 risers
    #   of 160) however tall the walls are; the walls above the ceiling are a void, reported.
    tall_walls = read_dxf(STAIRS, 3600, ceiling_height=3000, building_type="residential", params=PARAMS)
    f = _floor(tall_walls)
    (s,) = f.stairs
    assert f.finished_level_mm == 200 and f.ceilings[0].elevation.value == 3200
    assert s.total_rise.value == 3200 == 3400 - f.finished_level_mm
    assert s.riser_count == 20 and s.riser_height.value == 160
    assert "walls_above_ceiling" in _codes(tall_walls)
    # raising the CEILING raises the storey, the next floor and the stair together
    higher = read_dxf(STAIRS, 3600, ceiling_height=3300, building_type="residential", params=PARAMS)
    (s2,) = _floor(higher).stairs
    assert _floor(higher).ceilings[0].elevation.value == 3500  # the next slab's underside; next finished floor 3700
    assert s2.total_rise.value == 3500 == 3700 - 200 and s2.riser_count == 22  # 3500 / 160 = 21.9 -> 22
    assert "walls_above_ceiling" in _codes(higher)  # 3600 walls vs 3300 ceiling: still above
    level = read_dxf(STAIRS, 3400, ceiling_height=3400, building_type="residential", params=PARAMS)
    assert "walls_above_ceiling" not in _codes(level)


def test_walls_above_ceiling_is_only_reported_for_values_the_user_gave():
    # the commercial preset itself has walls (3000) above the ceiling (2700): nothing to report
    assert "walls_above_ceiling" not in _codes(read_dxf(STAIRS, building_type="commercial"))
    assert "walls_above_ceiling" in _codes(read_dxf(STAIRS, 3300, building_type="commercial"))


def test_regenerated_stairs_follow_the_ceiling_not_the_walls_through_the_job_route(client):
    pid = client.post(P, json={"name": "S"}).json()["project_id"]
    up = client.post("/api/v1/uploads", content=STAIRS.read_bytes()).json()["upload_id"]
    r = client.post(f"/api/v1/jobs/projects/{pid}/floors", json={"upload_id": up, "floor_name": "G", "elevation": 0, "ceiling_height": 3000, "wall_height": 3000})
    jobs.execute(r.json()["job_id"])

    def floor():
        gid = client.get(f"{P}/{pid}").json()["floors"][0]["generation_id"]
        return client.get(f"/api/v1/generations/{gid}/artifacts/canonical").json()["buildings"][0]["floors"][0]

    def stair():
        return floor()["stairs"][0]["total_rise"]["value"]

    assert stair() == 3200
    # (parameters, total rise = ceiling + 200 slab, walls above the ceiling reported?)
    for body, want, void in (
        ({"ceiling_height": 4000}, 4200, False),  # the storey rises: stair, ceiling plane, next floor
        ({"wall_height": 5000}, 4200, True),  # walls above the 4000 ceiling: the stair stays, and it is said
        ({"ceiling_height": 3000, "wall_height": 3000}, 3200, False),
    ):
        r = client.post(f"/api/v1/jobs/projects/{pid}/parameters", json=body)
        jobs.execute(r.json()["job_id"])
        assert stair() == want, body
        issues = client.get(f"/api/v1/jobs/{r.json()['job_id']}").json()["result"]["issues"]
        assert ("walls_above_ceiling" in [i["code"] for i in issues]) is void, body
