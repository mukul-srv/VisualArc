"""Generate synthetic Fixture Roofs: one rectangular building with a roof-plan outline, mm units.

Run: cd services/api && uv run python ../../scripts/make_fixture_roofs.py [--expected]
`--expected` also rewrites fixtures/expected/fixture_roofs.canonical.json (read with the
residential preset: gable roof at 30 degrees, both assumed, wall height 3000, ceiling 3000).

Plan (mm), all walls 200 thick: outer face (0,0)-(6400,4400); clear room (200,200)-(6200,4200).
  roof-plan outline  A-ROOF closed rectangle (-300,-300)-(6700,4700) = 7000 x 5000 (eaves)
  gable ridge along x (the long side); span 5000, ridge rise = 2500 * tan(30 deg) = 1443.38 mm.
Without the A-ROOF outline the roof is taken from the walls plus a 300 mm eave overhang, which
gives the same 7000 x 5000 footprint. Walls = paired boundary lines on A-WALL; floor = A-FLOR.
"""

import sys
from pathlib import Path

import ezdxf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "input" / "fixture_roofs.dxf"
EXPECTED = ROOT / "fixtures" / "expected" / "fixture_roofs.canonical.json"

OUTER = [(0, 0), (6400, 0), (6400, 4400), (0, 4400)]
INNER = [(200, 200), (6200, 200), (6200, 4200), (200, 4200)]
ROOF = [(-300, -300), (6700, -300), (6700, 4700), (-300, 4700)]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    for name in ("A-WALL", "A-FLOR", "A-ROOF"):
        doc.layers.add(name)
    msp = doc.modelspace()
    for loop in (OUTER, INNER):
        for i, a in enumerate(loop):
            msp.add_line(a, loop[(i + 1) % len(loop)], dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline(INNER, close=True, dxfattribs={"layer": "A-FLOR"})
    msp.add_lwpolyline(ROOF, close=True, dxfattribs={"layer": "A-ROOF"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"wrote {OUT}")
    if "--expected" in sys.argv:
        from api.engine.adapters.dxf.reader import read_dxf

        p = read_dxf(OUT, 3000, ceiling_height=3000, building_type="residential")
        EXPECTED.write_text(p.model_dump_json(indent=2) + "\n", "utf-8")
        print(f"wrote {EXPECTED}")


if __name__ == "__main__":
    main()
