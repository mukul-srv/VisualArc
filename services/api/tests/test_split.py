"""B8: floor split of a consolidated DXF (detection, scoped reading, endpoint).

Expectations come from the generator's constants (scripts/make_fixture_f.py).
"""

import importlib.util
from dataclasses import replace
from pathlib import Path

import ezdxf
import pytest
import trimesh
from fastapi.testclient import TestClient

from api.engine.adapters.dxf.reader import load_doc, read_dxf
from api.engine.adapters.dxf.split import FloorScope, detect_floors
from api.engine.settings import DEFAULTS, Settings
from api.main import app

ROOT = Path(__file__).resolve().parents[3]
INPUT = ROOT / "fixtures" / "input"
_spec = importlib.util.spec_from_file_location("make_fixture_f", ROOT / "scripts" / "make_fixture_f.py")
f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f)
H = {"wall_height": 3000, "ceiling_height": 3000}
SIZES = [(f.W1, f.H1), (f.W2, f.H2)]


def _split(name="fixture_f.dxf", settings=DEFAULTS):
    return detect_floors(load_doc(INPUT / name), 1.0, settings)


def _codes(issues):
    return [i.code for i in issues]


# --- detection ---------------------------------------------------------------


def test_spatial_split_candidates_from_generator_constants():
    s = _split()
    assert [c.key for c in s.candidates] == ["cluster-1", "cluster-2"]
    for c, (x0, y0, w, h) in zip(s.candidates, f.FLOORS):
        assert c.bbox == (x0, y0, x0 + w, y0 + h)
        d = c.to_dict()
        assert d["proposed_offset"] == {"x": x0, "y": y0, "source": "inferred"}
        assert d["entity_counts"] == {"LINE": 8, "LWPOLYLINE": 1}
        assert d["sources"]  # refs to the wall/boundary entities


def test_prefix_split_candidates():
    s = _split("fixture_f2.dxf")
    assert [c.key for c in s.candidates] == ["L1", "L2"]
    for c, (w, h) in zip(s.candidates, SIZES):
        assert c.bbox == (0, 0, w, h)  # drawn on top of each other
        assert c.to_dict()["proposed_offset"] == {"x": 0, "y": 0, "source": "inferred"}


@pytest.mark.parametrize("name", ["fixture_f.dxf", "fixture_f2.dxf"])
def test_non_floor_content_is_reported_with_sources(name):
    s = _split(name)
    by_layer = {i.message.split(":")[0]: i for i in s.issues}
    assert set(by_layer) == {"layer A-ROOF", "layer A-ANNO-TTLB"}
    assert all(i.code == "content_not_reconstructed" and i.severity == "warning" for i in s.issues)
    assert len(by_layer["layer A-ROOF"].sources) == 1  # the roof outline
    assert len(by_layer["layer A-ANNO-TTLB"].sources) == 2  # frame + text
    assert "1 TEXT" in by_layer["layer A-ANNO-TTLB"].message


def test_gap_threshold_boundary():
    # the floors' boxes are exactly GAP apart; "within the gap" merges
    assert len(_split(settings=replace(DEFAULTS, floor_gap_mm=f.GAP)).candidates) == 1
    assert len(_split(settings=replace(DEFAULTS, floor_gap_mm=f.GAP - 1)).candidates) == 2


def test_cluster_without_walls_and_stray_entities_are_reported(tmp_path):
    doc = ezdxf.readfile(INPUT / "fixture_f.dxf")
    msp = doc.modelspace()
    far = 10 * f.GAP
    msp.add_lwpolyline([(far, 0), (far + 1000, 0), (far + 1000, 1000), (far, 1000)], close=True,
                       dxfattribs={"layer": "A-FLOR"})  # boundary only, no walls
    msp.add_line((far, far), (far + 10, far), dxfattribs={"layer": "A-FURN"})  # in no candidate
    s = detect_floors(doc, 1.0)
    assert len(s.candidates) == 2
    msgs = " | ".join(i.message for i in s.issues)
    assert "cluster without walls" in msgs and "outside every floor candidate" in msgs


@pytest.mark.parametrize(
    "name",
    ["fixture_a.dxf", "fixture_b.dxf", "fixture_c.dxf", "fixture_d.dxf", "fixture_g.dxf", "fixture_openings.dxf"],
)
def test_single_floor_files_unchanged(name):
    assert len(_split(name).candidates) <= 1
    p = read_dxf(INPUT / name, 3000, ceiling_height=3000)
    assert "floor_split_unconfirmed" not in _codes(p.issues)
    assert p.buildings[0].floors[0].plan_offset is None


def test_settings_validation():
    with pytest.raises(ValueError):
        Settings(floor_prefix_pattern=r"^L\d+\|")  # no group for the key
    with pytest.raises(ValueError):
        Settings(floor_gap_mm=0)


# --- reading one floor -------------------------------------------------------


def _scope(name, key, offset):
    c = next(c for c in _split(name).candidates if c.key == key)
    return FloorScope(c.handles, offset)


def _extent(floor):
    pts = [p for b in floor.boundaries for p in b.polygon]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


@pytest.mark.parametrize("offset", [(f.FLOOR2_X, 0), (f.FLOOR2_X + 123.5, -77.25)])
def test_scoped_floor_is_translated_and_keeps_its_dimensions(offset):
    p = read_dxf(INPUT / "fixture_f.dxf", 3000, ceiling_height=3000, scope=_scope("fixture_f.dxf", "cluster-2", offset))
    fl = p.buildings[0].floors[0]
    assert [i for i in p.issues if i.severity == "blocking"] == []
    x, y, w, h = _extent(fl)
    # inner boundary: source position minus offset, size untouched (no floor-1 geometry)
    assert (x, y) == pytest.approx((f.FLOOR2_X + f.EXT - offset[0], f.EXT - offset[1]), abs=1e-6)
    assert (w, h) == pytest.approx((f.W2 - 2 * f.EXT, f.H2 - 2 * f.EXT), abs=1e-6)
    assert [t.thickness.value for t in fl.walls] == pytest.approx([f.EXT] * 4, abs=1e-6)
    assert len(fl.boundaries) == 1 and len(fl.walls) == 4
    assert (fl.plan_offset.x, fl.plan_offset.y, fl.plan_offset.source) == (*offset, "user_provided")


def test_prefix_floor_reads_through_the_layer_remainder():
    for key, (w, h) in zip(("L1", "L2"), SIZES):
        p = read_dxf(INPUT / "fixture_f2.dxf", 3000, ceiling_height=3000, scope=_scope("fixture_f2.dxf", key, (0, 0)))
        fl = p.buildings[0].floors[0]
        assert [i for i in p.issues if i.severity == "blocking"] == []
        assert _extent(fl) == pytest.approx((f.EXT, f.EXT, w - 2 * f.EXT, h - 2 * f.EXT), abs=1e-6)
        # sources keep the ORIGINAL prefixed layer name
        assert {s.layer for t in fl.walls for s in t.sources} == {f"{key}|A-WALL"}


def test_unscoped_consolidated_read_blocks():
    for name in ("fixture_f.dxf", "fixture_f2.dxf"):
        p = read_dxf(INPUT / name, 3000, ceiling_height=3000)
        assert _codes(p.issues)[0] == "floor_split_unconfirmed" and p.issues[0].severity == "blocking"
        assert "content_not_reconstructed" in _codes(p.issues)
        assert p.buildings == []


# --- API ---------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _upload(client, name="fixture_f.dxf"):
    r = client.post("/api/v1/uploads", content=(INPUT / name).read_bytes())
    assert r.status_code == 201
    return r.json()


def _body(pre, names=("Ground", "First"), elevs=(0, 3200), **kw):
    floors = [
        {"key": c["key"], "name": n, "elevation": e,
         "offset_x": c["proposed_offset"]["x"], "offset_y": c["proposed_offset"]["y"]}
        for c, n, e in zip(pre["floor_candidates"], names, elevs)
    ]
    return {"project_name": "House", "floors": floors, **H, **kw}


def _post(client, pre, body):
    return client.post(f"/api/v1/uploads/{pre['upload_id']}/split", json=body)


@pytest.mark.parametrize("name", ["fixture_f.dxf", "fixture_f2.dxf"])
def test_preflight_lists_candidates_and_blocks(client, name):
    pre = _upload(client, name)
    assert [c["key"] for c in pre["floor_candidates"]] == [c.key for c in _split(name).candidates]
    codes = [i["code"] for i in pre["issues"]]
    assert "floor_split_unconfirmed" in codes and "content_not_reconstructed" in codes
    r = client.post("/api/v1/generations", json={"upload_id": pre["upload_id"], **H})
    assert r.status_code == 409
    assert "floor_split_unconfirmed" in [i["code"] for i in r.json()["issues"]]


def test_preflight_of_single_floor_file_has_no_candidates(client):
    pre = _upload(client, "fixture_a.dxf")
    assert pre["floor_candidates"] == []
    assert "floor_split_unconfirmed" not in [i["code"] for i in pre["issues"]]


def test_split_creates_project_with_one_generation_per_floor(client):
    pre = _upload(client)
    body = _body(pre, elevs=(0, 3200.5))
    body["floors"][1]["offset_x"] += 10  # the user edited a proposed offset
    r = _post(client, pre, body)
    assert r.status_code == 201, r.text
    out = r.json()
    m = client.get(f"/api/v1/projects/{out['project_id']}").json()
    assert [(x["name"], x["elevation"]["value"]) for x in m["floors"]] == [("Ground", 0), ("First", 3200.5)]
    assert {x["elevation"]["source"] for x in m["floors"]} == {"user_provided"}
    assert "content_not_reconstructed" in [i["code"] for i in out["issues"]]
    for fl, (w, h), c in zip(out["floors"], SIZES, body["floors"]):
        canon = client.get(fl["artifacts"]["canonical"]).json()
        cf = canon["buildings"][0]["floors"][0]
        assert cf["plan_offset"] == {"x": c["offset_x"], "y": c["offset_y"], "unit": "mm", "source": "user_provided"}
        assert "content_not_reconstructed" in [i["code"] for i in canon["issues"]]  # carried into the floor
        scene = trimesh.load(trimesh.util.wrap_as_stream(client.get(fl["artifacts"]["glb"]).content), file_type="glb")
        ext = scene.bounds[1] - scene.bounds[0]
        assert (ext[0], ext[2]) == pytest.approx((w / 1000, h / 1000), abs=1e-6)  # source floor size, in m


def test_split_prefix_variant(client):
    pre = _upload(client, "fixture_f2.dxf")
    r = _post(client, pre, _body(pre))
    assert r.status_code == 201, r.text
    assert len(r.json()["floors"]) == 2


def test_excluded_candidate_is_reported_not_built(client):
    pre = _upload(client)
    body = _body(pre)
    body["floors"][1] = {"key": body["floors"][1]["key"], "exclude": True}
    r = _post(client, pre, body)
    assert r.status_code == 201
    assert len(r.json()["floors"]) == 1
    assert any("excluded by the user" in i["message"] for i in r.json()["issues"])


def test_split_rejections(client):
    pre = _upload(client)
    k1, k2 = (c["key"] for c in pre["floor_candidates"])
    good = _body(pre)

    def bad(mut, status=422):
        b = _body(pre)
        mut(b)
        assert _post(client, pre, b).status_code == status

    bad(lambda b: b["floors"].pop())  # a candidate neither confirmed nor excluded
    bad(lambda b: b["floors"].append({**good["floors"][0], "key": "nope"}))  # unknown key
    bad(lambda b: b["floors"].append(b["floors"][0]))  # duplicate key
    bad(lambda b: b["floors"][1].update(name=" ground "))  # duplicate name
    bad(lambda b: b["floors"][1].update(elevation=0))  # duplicate elevation
    bad(lambda b: b["floors"][1].update(elevation="inf"))  # not finite
    bad(lambda b: b["floors"][1].update(offset_x="nan"))
    bad(lambda b: b["floors"][1].pop("name"))  # incomplete confirmation
    bad(lambda b: b.__setitem__("floors", [{"key": k1, "exclude": True}, {"key": k2, "exclude": True}]))
    assert _post(client, {"upload_id": "0" * 32}, good).status_code == 404
    single = _upload(client, "fixture_a.dxf")
    assert _post(client, single, good).status_code == 422  # nothing to confirm


def test_blocking_floor_creates_nothing(client, tmp_path):
    pre = _upload(client)
    body = _body(pre)
    del body["wall_height"]  # every floor now blocks
    r = _post(client, pre, body)
    assert r.status_code == 409
    j = r.json()
    assert set(j["floors"]) == {c["key"] for c in pre["floor_candidates"]}
    assert "wall_height_missing" in [i["code"] for i in j["issues"]]
    for d in ("projects", "generations"):
        assert not (tmp_path / d).exists() or not any((tmp_path / d).iterdir())
