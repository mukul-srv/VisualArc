from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from api.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "input"
GEN = "/api/v1/generations"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _upload(client, name="fixture_a.dxf") -> str:
    r = client.post("/api/v1/uploads", content=(FIXTURES / name).read_bytes())
    assert r.status_code == 201
    return r.json()["upload_id"]


def test_generation_success_serves_usable_glb(client):
    r = client.post(GEN, json={"upload_id": _upload(client), "wall_height": 3000, "ceiling_height": 3000})
    assert r.status_code == 201
    body = r.json()
    assert set(body["artifacts"]) == {"glb", "meta", "canonical", "report"}
    glb = client.get(body["artifacts"]["glb"])
    assert glb.status_code == 200 and glb.headers["content-type"] == "model/gltf-binary"
    scene = trimesh.load(trimesh.util.wrap_as_stream(glb.content), file_type="glb")
    assert scene.bounds.round(6).tolist() == [[0, -0.2, -5.2], [8.2, 3.0, 0]]  # y min: the default 200 mm slab
    assert "# Verification report" in client.get(body["artifacts"]["report"]).text


def _canon(client, r):
    return client.get(r.json()["artifacts"]["canonical"]).json()["buildings"][0]["floors"][0]


@pytest.mark.parametrize(
    "kind, wall, ceiling, door, window, sill",
    [
        (None, 2700, 2700, 2100, 1200, 900),  # residential is the default
        ("residential", 2700, 2700, 2100, 1200, 900),
        ("commercial", 3000, 2700, 2100, 1500, 900),
    ],
)
def test_missing_heights_come_from_preset_tagged_defaulted(client, kind, wall, ceiling, door, window, sill):
    body = {"upload_id": _upload(client, "fixture_openings.dxf")}
    if kind:
        body["building_type"] = kind
    r = client.post(GEN, json=body)
    assert r.status_code == 201
    floor = _canon(client, r)
    assert {w["height"]["value"] for w in floor["walls"]} == {wall}
    assert {w["height"]["source"] for w in floor["walls"]} == {"defaulted"}
    assert (floor["ceiling_height"]["value"], floor["ceiling_height"]["source"]) == (ceiling, "defaulted")
    by = {k: [o for o in floor["openings"] if o["kind"] == k] for k in ("door", "window")}
    assert {o["height"]["value"] for o in by["door"]} == {door}
    assert {o["height"]["value"] for o in by["window"]} == {window}
    assert {o["sill_height"]["value"] for o in by["window"]} == {sill}
    for o in by["door"] + by["window"]:
        assert o["height"]["source"] == o["sill_height"]["source"] == "defaulted"
    msgs = {i["code"]: i["message"] for i in r.json()["issues"] if i["severity"] == "warning"}
    assert f"assumed {wall} mm ({kind or 'residential'} default)" in msgs["wall_height_defaulted"]
    assert f"assumed {ceiling} mm" in msgs["ceiling_height_defaulted"]
    assert not {i["code"] for i in r.json()["issues"] if i["severity"] == "blocking"}


def test_user_values_win_over_preset_and_stay_user_provided(client):
    r = client.post(
        GEN,
        json={
            "upload_id": _upload(client, "fixture_openings.dxf"), "building_type": "commercial",
            "wall_height": 3300, "ceiling_height": 3100, "door_height": 2000,
        },
    )
    assert r.status_code == 201
    floor = _canon(client, r)
    assert {(w["height"]["value"], w["height"]["source"]) for w in floor["walls"]} == {(3300, "user_provided")}
    assert (floor["ceiling_height"]["value"], floor["ceiling_height"]["source"]) == (3100, "user_provided")
    doors = [o for o in floor["openings"] if o["kind"] == "door"]
    assert {(o["height"]["value"], o["height"]["source"]) for o in doors} == {(2000, "user_provided")}
    windows = [o for o in floor["openings"] if o["kind"] == "window"]
    assert {o["height"]["value"] for o in windows} == {1500}  # untouched ones still follow the preset
    codes = {i["code"] for i in r.json()["issues"]}
    assert not codes & {"wall_height_defaulted", "ceiling_height_defaulted"}


def test_unknown_building_type_is_422(client):
    body = {"upload_id": "x", "building_type": "castle"}
    assert client.post(GEN, json=body).status_code == 422


def test_presets_endpoint_serves_settings(client):
    from dataclasses import asdict

    from api.engine.settings import DEFAULTS

    r = client.get("/api/v1/presets")
    assert r.status_code == 200
    assert r.json() == {k: asdict(v) for k, v in DEFAULTS.building_presets}


def test_openings_parameters_are_applied(client):
    uid = _upload(client, "fixture_openings.dxf")
    r = client.post(
        GEN, json={"upload_id": uid, "wall_height": 3000, "ceiling_height": 3000, "door_height": 2000}
    )
    assert r.status_code == 201
    canon = client.get(r.json()["artifacts"]["canonical"]).json()
    doors = [
        o for o in canon["buildings"][0]["floors"][0]["openings"] if o["kind"] == "door"
    ]
    assert doors and {o["height"]["value"] for o in doors} == {2000}
    assert {o["height"]["source"] for o in doors} == {"user_provided"}


@pytest.mark.parametrize(
    "body, status",
    [
        ({"upload_id": "0" * 32, "wall_height": 3000, "ceiling_height": 3000}, 404),
        ({"upload_id": "../../etc/passwd", "wall_height": 3000, "ceiling_height": 3000}, 404),
        ({"upload_id": "x", "wall_height": -1}, 422),
        ({"upload_id": "x", "wall_height": 3000, "ceiling_height": 3000, "units": "parsecs"}, 422),
        ({"upload_id": "x", "wall_height": 3000, "ceiling_height": 3000, "bogus": 1}, 422),
    ],
)
def test_bad_requests(client, body, status):
    assert client.post(GEN, json=body).status_code == status


def test_unitless_needs_units_then_succeeds(client, tmp_path):
    import io

    import ezdxf

    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 0
    for a, b in [((0, 0), (4, 0)), ((0, 0.2), (4, 0.2))]:
        doc.modelspace().add_line(a, b, dxfattribs={"layer": "A-WALL"})
    buf = io.StringIO()
    doc.write(buf)
    uid = client.post("/api/v1/uploads", content=buf.getvalue().encode()).json()[
        "upload_id"
    ]
    r = client.post(GEN, json={"upload_id": uid})  # presets fill heights, never units
    assert r.status_code == 409
    assert "units_missing" in {i["code"] for i in r.json()["issues"]}
    r = client.post(GEN, json={"upload_id": uid, "wall_height": 3000, "ceiling_height": 3000, "units": "m"})
    assert r.status_code == 201


@pytest.mark.parametrize(
    "gid, name",
    [
        ("0" * 32, "glb"),
        ("..", "glb"),
        ("%2e%2e", "glb"),
        ("0" * 32, "../x"),
        ("0" * 32, "secret"),
    ],
)
def test_artifact_unknown_or_traversal_is_404(client, gid, name):
    assert client.get(f"{GEN}/{gid}/artifacts/{name}").status_code == 404


def test_missing_ceiling_height_is_a_tagged_warning_not_a_block(client):
    uid = _upload(client)
    r = client.post(GEN, json={"upload_id": uid, "wall_height": 3000})
    assert r.status_code == 201
    assert {i["code"] for i in r.json()["issues"]} == {
        "ceiling_height_defaulted", "elevation_defaulted", "wall_role_inferred", "slab_thickness_defaulted"
    }
    r = client.post(GEN, json={"upload_id": uid, "wall_height": 3000, "ceiling_height": 2600})
    assert r.status_code == 201
    assert client.post(GEN, json={"upload_id": uid, "ceiling_height": 0}).status_code == 422
