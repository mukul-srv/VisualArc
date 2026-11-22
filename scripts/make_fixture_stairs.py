"""Generate synthetic Fixture Stairs: one room with a stair and a ramp, mm units.

Run: cd services/api && uv run python ../../scripts/make_fixture_stairs.py [--expected]
`--expected` also rewrites fixtures/expected/fixture_stairs.canonical.json (read with the
residential preset, ceiling 3000, stair_rise 160 and stair_run 250 given by the user).

Plan (mm), all walls 200 thick: outer face (0,0)-(6400,4400); clear room (200,200)-(6200,4200).
  stair  A-FLOR-STRS closed rectangle (450,500)-(5200,1500) + arrow LINE (450,1000)->(5200,1000)
         length 4750, width 1000. Total rise = ceiling 3000 + default slab 200 = 3200.
         rise 160 -> 20 risers, 19 treads of 4750 / 19 = 250 (= the run parameter), riser 160.
  ramp   A-FLOR-RAMP closed rectangle (450,2500)-(5200,3500) + arrow LINE (450,3000)->(5200,3000)
         length 4750; rises 3200 (a full floor) -> slope 3200/4750 (steeper than 1:12, reported).
Walls = paired boundary lines on A-WALL (outer + inner loop); floor = closed LWPOLYLINE on A-FLOR.
"""

import sys
from pathlib import Path

import ezdxf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "input" / "fixture_stairs.dxf"
EXPECTED = ROOT / "fixtures" / "expected" / "fixture_stairs.canonical.json"

OUTER = [(0, 0), (6400, 0), (6400, 4400), (0, 4400)]
INNER = [(200, 200), (6200, 200), (6200, 4200), (200, 4200)]
STAIR = ((450, 500), (5200, 1500))
RAMP = ((450, 2500), (5200, 3500))


def rect(a, b):
    return [(a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1])]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    for name in ("A-WALL", "A-FLOR", "A-FLOR-STRS", "A-FLOR-RAMP"):
        doc.layers.add(name)
    msp = doc.modelspace()
    for loop in (OUTER, INNER):
        for i, a in enumerate(loop):
            msp.add_line(a, loop[(i + 1) % len(loop)], dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline(INNER, close=True, dxfattribs={"layer": "A-FLOR"})
    for layer, (a, b) in (("A-FLOR-STRS", STAIR), ("A-FLOR-RAMP", RAMP)):
        msp.add_lwpolyline(rect(a, b), close=True, dxfattribs={"layer": layer})
        mid = (a[1] + b[1]) / 2
        msp.add_line((a[0], mid), (b[0], mid), dxfattribs={"layer": layer})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"wrote {OUT}")
    if "--expected" in sys.argv:
        from api.engine.adapters.dxf.reader import read_dxf

        p = read_dxf(
            OUT, 3000, ceiling_height=3000, building_type="residential",
            params={"stair_rise": 160, "stair_run": 250},
        )
        EXPECTED.write_text(p.model_dump_json(indent=2) + "\n", "utf-8")
        print(f"wrote {EXPECTED}")


if __name__ == "__main__":
    main()
