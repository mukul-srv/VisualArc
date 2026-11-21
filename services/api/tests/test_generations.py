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
    assert scene.bounds.round(6).tolist() == [[0, 0, -5.2], [8.2, 3.0, 0]]
    assert "# Verification report" in client.get(body["artifacts"]["report"]).text


def test_missing_height_blocked_409_with_structured_issues(client, tmp_path):
    r = client.post(GEN, json={"upload_id": _upload(client)})
    assert r.status_code == 409
    codes = {i["code"]: i["severity"] for i in r.json()["issues"]}
    assert codes["wall_height_missing"] == "blocking"
    assert not (tmp_path / "generations").exists()  # nothing stored on a block


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
    r = client.post(GEN, json={"upload_id": uid, "wall_height": 3000, "ceiling_height": 3000})
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


def test_missing_ceiling_height_blocked_409_then_ok(client):
    uid = _upload(client)
    r = client.post(GEN, json={"upload_id": uid, "wall_height": 3000})
    assert r.status_code == 409
    assert {i["code"] for i in r.json()["issues"]} == {
        "ceiling_height_missing", "elevation_defaulted", "wall_role_inferred"
    }
    r = client.post(GEN, json={"upload_id": uid, "wall_height": 3000, "ceiling_height": 2600})
    assert r.status_code == 201
    assert client.post(GEN, json={"upload_id": uid, "ceiling_height": 0}).status_code == 422
