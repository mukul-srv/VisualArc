"""Generate synthetic Fixture B: one L-shaped room (non-rectangular, one reflex corner), mm units.

Run: cd services/api && uv run python ../../scripts/make_fixture_b.py

Plan (mm), all walls 200 thick:
  outer face  (0,0) (6000,0) (6000,3000) (3000,3000) (3000,5000) (0,5000)
  clear room  (200,200) (5800,200) (5800,2800) (2800,2800) (2800,4800) (200,4800)
Walls = paired boundary lines on A-WALL (outer + inner loop); floor = closed LWPOLYLINE on A-FLOR.
New vs A: reflex corner, non-rect floor, 6-vertex boundary. No wall height in the DXF.
"""

from pathlib import Path

import ezdxf

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "fixture_b.dxf"

OUTER = [(0, 0), (6000, 0), (6000, 3000), (3000, 3000), (3000, 5000), (0, 5000)]
INNER = [(200, 200), (5800, 200), (5800, 2800), (2800, 2800), (2800, 4800), (200, 4800)]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    doc.layers.add("A-WALL")
    doc.layers.add("A-FLOR")
    msp = doc.modelspace()
    for loop in (OUTER, INNER):
        for i, a in enumerate(loop):
            msp.add_line(a, loop[(i + 1) % len(loop)], dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline(INNER, close=True, dxfattribs={"layer": "A-FLOR"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
