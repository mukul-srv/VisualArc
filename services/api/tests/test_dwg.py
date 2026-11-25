"""DWG upload (Phase 1/23): ODA File Converter found, run and failing, all with a fake converter."""

import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.engine.adapters.dwg import convert
from api.engine.adapters.dxf.reader import InputError
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
DWG = b"AC1032" + b"\0" * 100  # the header is all the sniff reads; the converter is faked


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "_candidates", list)
    monkeypatch.setattr(convert.shutil, "which", lambda _: None)
    monkeypatch.delenv(convert.ENV, raising=False)
    return TestClient(app)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A converter file the env var points at, and a subprocess.run that stands in for running it."""
    exe = tmp_path / "ODAFileConverter"
    exe.write_text("")
    exe.chmod(0o755)
    monkeypatch.setenv(convert.ENV, str(exe))
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        out = Path(argv[2])
        (out / "drawing.dxf").write_bytes((INPUT / "fixture_a.dxf").read_bytes())
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convert.subprocess, "run", run)
    return calls


def test_is_dwg_sniffs_the_header(tmp_path):
    (tmp_path / "a.bin").write_bytes(DWG)
    assert convert.is_dwg(tmp_path / "a.bin") and not convert.is_dwg(INPUT / "fixture_a.dxf")


def test_find_converter_env_var_and_missing(client, tmp_path, monkeypatch):
    assert convert.find_converter() is None
    monkeypatch.setenv(convert.ENV, str(tmp_path / "nope"))
    with pytest.raises(InputError, match=convert.ENV):  # a wrong path is an error, not a silent fallback
        convert.find_converter()
    exe = tmp_path / "ODAFileConverter"
    exe.write_text("")
    exe.chmod(0o755)
    monkeypatch.setenv(convert.ENV, str(exe))
    assert convert.find_converter() == exe.resolve()


@pytest.mark.skipif(os.name == "nt", reason="the executable bit does not exist on Windows")
def test_a_non_executable_file_is_not_a_converter(client, tmp_path, monkeypatch):
    f = tmp_path / "ODAFileConverter"
    f.write_text("")
    f.chmod(0o644)
    monkeypatch.setenv(convert.ENV, str(f))
    with pytest.raises(InputError):
        convert.find_converter()


def test_dwg_upload_is_converted_and_read_as_dxf(client, fake):
    r = client.post("/api/v1/uploads", params={"filename": "plan.dwg"}, content=DWG)
    assert r.status_code == 201 and r.json()["inventory"]["layers"]
    argv, kw = fake[0]
    assert kw["shell"] is False and kw["timeout"] > 0 and isinstance(argv, list)
    assert argv[3:5] == ["ACAD2018", "DXF"] and Path(argv[1]).name == "in"  # fixed names, no client string
    g = client.post("/api/v1/generations", json={"upload_id": r.json()["upload_id"], "wall_height": 3000,
                                                 "ceiling_height": 3000})
    assert g.status_code == 201  # the stored file is the DXF: the rest of the pipeline is unchanged


def test_missing_converter_explains_how_to_install(client):
    r = client.post("/api/v1/uploads", content=DWG)
    assert r.status_code == 422
    assert "ODA File Converter" in r.json()["detail"] and "opendesign.com" in r.json()["detail"]


def test_converter_failure_and_timeout_are_clear_errors(client, fake, monkeypatch):
    monkeypatch.setattr(convert.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "boom"))
    r = client.post("/api/v1/uploads", content=DWG)
    assert r.status_code == 422 and "could not convert" in r.json()["detail"] and "boom" not in r.json()["detail"]

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(convert.subprocess, "run", slow)
    r = client.post("/api/v1/uploads", content=DWG)
    assert r.status_code == 422 and "longer than" in r.json()["detail"]


def test_exit_zero_without_output_is_a_failure(client, fake, monkeypatch):
    monkeypatch.setattr(convert.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""))
    assert client.post("/api/v1/uploads", content=DWG).status_code == 422
