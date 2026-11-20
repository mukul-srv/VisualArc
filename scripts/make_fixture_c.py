"""Generate synthetic Fixture C: Fixture A drawn with a different convention.

Run: cd services/api && uv run python ../../scripts/make_fixture_c.py

Same building as Fixture A (see make_fixture_a.py) but:
  - walls are three closed LWPOLYLINE rings (outer face, room 1 inner face,
    room 2 inner face) instead of 12 LINEs, so the interior wall's faces are
    the rings' adjacent edges and exterior inner faces stop at them;
  - layer names are lower case ("a-wall", "a-flor"); matching is
    case-insensitive.
Canonical geometry must equal Fixture A's, ignoring source handles/layer case.
"""

from pathlib import Path

import ezdxf

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "fixture_c.dxf"

W, H, EXT = 8200, 5200, 200
X_INT0, X_INT1 = 4200, 4300

RINGS = [
    [(0, 0), (W, 0), (W, H), (0, H)],
    [(EXT, EXT), (X_INT0, EXT), (X_INT0, H - EXT), (EXT, H - EXT)],
    [(X_INT1, EXT), (W - EXT, EXT), (W - EXT, H - EXT), (X_INT1, H - EXT)],
]
ROOMS = RINGS[1:]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    doc.layers.add("a-wall")
    doc.layers.add("a-flor")
    msp = doc.modelspace()
    for pts in RINGS:
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "a-wall"})
    for pts in ROOMS:
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "a-flor"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
