import json
from pathlib import Path

import ezdxf

from api.cli import main
from api.engine.adapters.dxf.inspect import build_inventory

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
FIXTURE_A = FIXTURES / "input" / "fixture_a.dxf"


def test_fixture_a_known_facts() -> None:
    inv = build_inventory(FIXTURE_A)
    assert inv["units"] == {"insunits": 4, "name": "Millimeters"}
    assert inv["entity_counts"] == {"LINE": 12, "LWPOLYLINE": 2}
    assert len(inv["entities_by_layer"]["A-WALL"]["LINE"]) == 12
    assert len(inv["entities_by_layer"]["A-FLOR"]["LWPOLYLINE"]) == 2
    assert inv["extents"] == {"min": [0.0, 0.0, 0.0], "max": [8200.0, 5200.0, 0.0]}


def test_fixture_a_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "inv.json"
    main(["inspect", str(FIXTURE_A), "--out", str(out)])
    expected = json.loads(
        (FIXTURES / "expected" / "fixture_a.inventory.json").read_text()
    )
    assert json.loads(out.read_text()) == expected


def test_unitless_dxf_reports_no_unit_name(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 0
    path = tmp_path / "unitless.dxf"
    doc.saveas(path)
    inv = build_inventory(path)
    assert inv["units"] == {"insunits": 0, "name": None}
    assert inv["extents"] is None
