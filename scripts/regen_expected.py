"""Regenerate fixtures/expected/*.canonical.json after a schema change (never edit them by hand).

Run from services/api: `uv run python ../../scripts/regen_expected.py`. Each fixture is read exactly as the test
that compares against it reads it (same arguments), so the diff of a regeneration shows only what the schema
change did.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
import test_columns_balconies, test_roofs, test_stairs  # noqa: E402
from api.cli import main  # noqa: E402

EXPECTED, INPUT = ROOT / "fixtures/expected", ROOT / "fixtures/input"
CLI = {"fixture_a": "fixture_a.dxf", "fixture_b": "fixture_b.dxf", "fixture_openings": "fixture_openings.dxf"}
TESTS = {"fixture_columns": test_columns_balconies, "fixture_roofs": test_roofs, "fixture_stairs": test_stairs}

for name, dxf in CLI.items():
    main(["interpret", str(INPUT / dxf), "--wall-height", "3000", "--ceiling-height", "3000",
          "--out", str(EXPECTED / f"{name}.canonical.json")])
for name, module in TESTS.items():  # the test module's own reader, so the arguments cannot drift
    project = module._read()
    (EXPECTED / f"{name}.canonical.json").write_text(project.model_dump_json(indent=2) + "\n", encoding="utf-8")

# the report snapshots (read as test_report.py reads them, compared against the canonical files above)
from api.engine.adapters.dxf.reader import read_dxf  # noqa: E402
from api.engine.canonical.model import Project  # noqa: E402
from api.engine.exporters.report import build_report  # noqa: E402

for name in ("fixture_a", "fixture_openings"):
    expected = Project.model_validate_json((EXPECTED / f"{name}.canonical.json").read_text(encoding="utf-8"))
    report = build_report(read_dxf(INPUT / f"{name}.dxf", 3000, ceiling_height=3000), expected)
    (EXPECTED / f"{name}.report.md").write_text(report, encoding="utf-8")
