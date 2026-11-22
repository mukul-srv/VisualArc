"""Generate synthetic Fixture Columns: one room with two columns and a balcony, mm units.

Run: cd services/api && uv run python ../../scripts/make_fixture_columns.py [--expected]
`--expected` also rewrites fixtures/expected/fixture_columns.canonical.json (read with the
residential preset, so slab, railing and the other assumed values are included).

Plan (mm), all walls 200 thick:
  outer face (0,0)-(6400,4400); clear room (200,200)-(6200,4200) = 6000 x 4000 = 24 m2
  column C1  A-COLS closed rectangle (1000,1000)-(1300,1300)       300 x 300
  column C2  A-COLS circle centre (4000,2000), radius 200
  balcony    A-BALC closed rectangle (1000,-1500)-(5000,0): 4000 x 1500 = 6 m2, attached to the
             south wall's outer face (y=0); free edges (railing) = bottom 4000 + two sides 1500
Walls = paired boundary lines on A-WALL (outer + inner loop); floor = closed LWPOLYLINE on A-FLOR.
No wall or ceiling height in the DXF.
"""

import sys
from pathlib import Path

import ezdxf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "input" / "fixture_columns.dxf"
EXPECTED = ROOT / "fixtures" / "expected" / "fixture_columns.canonical.json"

OUTER = [(0, 0), (6400, 0), (6400, 4400), (0, 4400)]
INNER = [(200, 200), (6200, 200), (6200, 4200), (200, 4200)]
COLUMN_RECT = [(1000, 1000), (1300, 1000), (1300, 1300), (1000, 1300)]
COLUMN_CIRCLE = ((4000, 2000), 200)
BALCONY = [(1000, -1500), (5000, -1500), (5000, 0), (1000, 0)]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    for name in ("A-WALL", "A-FLOR", "A-COLS", "A-BALC"):
        doc.layers.add(name)
    msp = doc.modelspace()
    for loop in (OUTER, INNER):
        for i, a in enumerate(loop):
            msp.add_line(a, loop[(i + 1) % len(loop)], dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline(INNER, close=True, dxfattribs={"layer": "A-FLOR"})
    msp.add_lwpolyline(COLUMN_RECT, close=True, dxfattribs={"layer": "A-COLS"})
    msp.add_circle(*COLUMN_CIRCLE, dxfattribs={"layer": "A-COLS"})
    msp.add_lwpolyline(BALCONY, close=True, dxfattribs={"layer": "A-BALC"})
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
