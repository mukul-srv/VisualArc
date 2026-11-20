"""Bad input is rejected cleanly: exit 3, one-line stderr, no traceback, no output."""

from pathlib import Path

import pytest

from api.cli import main

FIXTURE_A = Path(__file__).resolve().parents[3] / "fixtures" / "input" / "fixture_a.dxf"


def _run(capsys, *argv):
    with pytest.raises(SystemExit) as exc:
        main([str(a) for a in argv])
    err = capsys.readouterr().err
    assert "Traceback" not in err
    return exc.value.code, err


def _bad(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    good = FIXTURE_A.read_bytes()
    if name == "renamed.txt":
        p.write_text("hello, this is not a DXF\n")
    elif name == "empty.dxf":
        p.write_bytes(b"")
    elif name == "truncated.dxf":
        p.write_bytes(good[: len(good) // 2])
    elif name == "garbage.dxf":
        p.write_bytes(bytes(range(256)) * 20)
    return p


@pytest.mark.parametrize(
    "name", ["renamed.txt", "empty.dxf", "truncated.dxf", "garbage.dxf"]
)
@pytest.mark.parametrize("cmd", ["inspect", "interpret", "build"])
def test_bad_content_rejected(tmp_path, capsys, name, cmd) -> None:
    out = tmp_path / "out"
    extra = ["--out", out] if cmd == "build" else []
    code, err = _run(capsys, cmd, _bad(tmp_path, name), *extra)
    assert code == 3
    assert err.startswith("error: ") and "DXF" in err
    assert not out.exists()


def test_missing_and_directory(tmp_path, capsys) -> None:
    for p in (tmp_path / "nope.dxf", tmp_path):
        code, err = _run(capsys, "inspect", p)
        assert code == 3 and err.startswith("error: not a readable file")


def test_oversized_rejected_and_flag_overrides(tmp_path, capsys) -> None:
    out = tmp_path / "o.json"
    code, err = _run(capsys, "interpret", FIXTURE_A, "--max-mb", "0.0001", "--out", out)
    assert code == 3 and "limit" in err and "provisional" in err
    assert not out.exists()
    # generous limit: passes the size check (exit 1 = blocking wall-height issue, not 3)
    code, _ = _run(capsys, "interpret", FIXTURE_A, "--max-mb", "100", "--out", out)
    assert code == 1 and out.exists()
