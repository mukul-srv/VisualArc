import io
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api.engine.settings import DEFAULTS
from api.main import app

FIXTURE_A = Path(__file__).resolve().parents[3] / "fixtures" / "input" / "fixture_a.dxf"
URL = "/api/v1/uploads"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _stored(tmp_path: Path) -> list[Path]:
    return list(tmp_path.iterdir())


def test_valid_upload_returns_preflight(client, tmp_path):
    r = client.post(URL, content=FIXTURE_A.read_bytes())
    assert r.status_code == 201
    body = r.json()
    assert len(body["upload_id"]) == 32
    assert body["inventory"]["layers"] and body["inventory"]["entity_counts"]
    assert body["needs"] == ["wall_height"]  # height is never in the DXF
    codes = {i["code"]: i["severity"] for i in body["issues"]}
    assert codes["wall_height_missing"] == "blocking"
    assert [p.name for p in _stored(tmp_path)] == [f"{body['upload_id']}.dxf"]


def test_unitless_upload_needs_units(client):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 0
    buf = io.StringIO()
    doc.write(buf)
    r = client.post(URL, content=buf.getvalue().encode())
    assert r.status_code == 201 and "units" in r.json()["needs"]


@pytest.mark.parametrize(
    "payload", [b"hello, not a dxf", FIXTURE_A.read_bytes()[:300], b""]
)
def test_invalid_upload_rejected_422_and_cleaned_up(client, tmp_path, payload):
    r = client.post(URL, content=payload)
    assert r.status_code == 422 and r.json()["detail"]
    assert "Traceback" not in r.text
    assert _stored(tmp_path) == []


def test_oversized_upload_rejected_413_and_cleaned_up(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.uploads.DEFAULTS", DEFAULTS.__class__(max_dxf_bytes=1000))
    r = client.post(URL, content=FIXTURE_A.read_bytes())
    assert r.status_code == 413
    assert _stored(tmp_path) == []


def test_oversized_chunked_upload_rejected_without_content_length(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr("api.uploads.DEFAULTS", DEFAULTS.__class__(max_dxf_bytes=1000))

    def gen():
        for _ in range(5):
            yield b"x" * 500

    assert client.post(URL, content=gen()).status_code == 413
    assert _stored(tmp_path) == []


def test_client_filename_never_used_as_path(client, tmp_path):
    r = client.post(
        URL,
        content=FIXTURE_A.read_bytes(),
        headers={
            "X-Filename": "../../evil.dxf",
            "Content-Disposition": "x; filename=../e",
        },
    )
    assert r.status_code == 201
    assert all(p.parent == tmp_path for p in _stored(tmp_path))


def test_error_message_does_not_leak_server_path(client, tmp_path):
    r = client.post(URL, content=b"hello, not a dxf")
    assert str(tmp_path) not in r.text and r.status_code == 422
