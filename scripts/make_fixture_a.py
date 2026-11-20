"""Generate synthetic Fixture A: two rectangular rooms, mm units.

Run: cd services/api && uv run python ../../scripts/make_fixture_a.py

Plan (mm), exterior walls 200 thick, interior wall 100 thick:
  outer face   (0,0)-(8200,5200)
  room 1 clear (200,200)-(4200,5000)   4000 x 4800
  interior wall x 4200..4300
  room 2 clear (4300,200)-(8000,5000)  3700 x 4800
Walls = paired boundary lines on A-WALL; floors = closed LWPOLYLINE on A-FLOR.
No wall height in the DXF on purpose (must come from the user).
"""

from pathlib import Path

import ezdxf

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "fixture_a.dxf"

W, H, EXT = 8200, 5200, 200
X_INT0, X_INT1 = 4200, 4300  # interior wall faces

# Each wall face as (start, end); one line per face.
WALL_LINES = [
    # outer faces
    ((0, 0), (W, 0)),
    ((W, 0), (W, H)),
    ((W, H), (0, H)),
    ((0, H), (0, 0)),
    # inner faces of exterior walls, split where interior wall meets them
    ((EXT, EXT), (X_INT0, EXT)),
    ((X_INT1, EXT), (W - EXT, EXT)),
    ((W - EXT, EXT), (W - EXT, H - EXT)),
    ((W - EXT, H - EXT), (X_INT1, H - EXT)),
    ((X_INT0, H - EXT), (EXT, H - EXT)),
    ((EXT, H - EXT), (EXT, EXT)),
    # interior wall faces
    ((X_INT0, EXT), (X_INT0, H - EXT)),
    ((X_INT1, EXT), (X_INT1, H - EXT)),
]

ROOMS = [
    [(EXT, EXT), (X_INT0, EXT), (X_INT0, H - EXT), (EXT, H - EXT)],
    [(X_INT1, EXT), (W - EXT, EXT), (W - EXT, H - EXT), (X_INT1, H - EXT)],
]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM  # $INSUNITS = 4
    doc.layers.add("A-WALL")
    doc.layers.add("A-FLOR")
    msp = doc.modelspace()
    for a, b in WALL_LINES:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    for pts in ROOMS:
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-FLOR"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
