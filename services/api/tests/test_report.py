from pathlib import Path

from api.cli import main
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import Project
from api.engine.exporters.report import _measured, build_report

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
INPUT, EXPECTED = FIXTURES / "input", FIXTURES / "expected"


def _snapshot(name: str) -> str:
    return (EXPECTED / f"{name}.report.md").read_text(encoding="utf-8")


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def test_fixture_a_report_snapshot():
    p = read_dxf(INPUT / "fixture_a.dxf", 3000, ceiling_height=3000)
    expected = Project.model_validate_json(
        (EXPECTED / "fixture_a.canonical.json").read_text(encoding="utf-8")
    )
    assert _norm(build_report(p, expected)) == _norm(_snapshot("fixture_a"))


def test_fixture_openings_report_snapshot():
    p = read_dxf(INPUT / "fixture_openings.dxf", 3000, ceiling_height=3000)
    expected = Project.model_validate_json(
        (EXPECTED / "fixture_openings.canonical.json").read_text(encoding="utf-8")
    )
    assert _norm(build_report(p, expected)) == _norm(_snapshot("fixture_openings"))


def test_every_non_extracted_value_appears_in_report():
    p = read_dxf(INPUT / "fixture_openings.dxf", 3000, ceiling_height=3000)
    report = build_report(p)
    flagged = [r for r in _measured(p) if r[2].source != "source_extracted"]
    assert len(flagged) > 20  # guards against a vacuous loop
    for eid, field, m, _ in flagged:
        line = next(
            l for l in report.splitlines() if l.startswith(f"| {eid} | {field} |")
        )
        assert m.source in line


def test_blocked_report_lists_blocking_issue_and_still_renders():
    p = read_dxf(INPUT / "fixture_a.dxf")  # no height -> blocking
    report = build_report(p)
    assert "**BLOCKED**" in report and "`wall_height_missing`" in report


def test_mismatch_is_marked():
    p = read_dxf(INPUT / "fixture_a.dxf", 3000, ceiling_height=3000)
    other = read_dxf(INPUT / "fixture_b.dxf", 3000, ceiling_height=3000)
    assert "**NO**" in build_report(p, other)


def test_cli_build_writes_report_even_when_blocked(tmp_path: Path):
    out = tmp_path / "o"
    try:
        main(["build", str(INPUT / "fixture_a.dxf"), "--out", str(out)])
    except SystemExit as e:
        assert e.code == 1
    assert "BLOCKED" in (out / "fixture_a.report.md").read_text(encoding="utf-8")
