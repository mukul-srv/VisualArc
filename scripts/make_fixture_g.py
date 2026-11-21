"""Generate synthetic Fixture G: wall roles drawn on role layers, mm units.

Run: cd services/api && uv run python ../../scripts/make_fixture_g.py

Plan (mm): exterior walls 200 thick on A-WALL-EXTR, two interior partitions
100 thick on A-WALL-INTR (one full-height at x 3000..3100, one in the right room
at y 2000..2100), floors on A-FLOR. No wall height in the DXF on purpose.
"""

from pathlib import Path

import ezdxf

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "fixture_g.dxf"

W, H, EXT = 6000, 4000, 200
PX0, PX1 = 3000, 3100  # vertical partition faces
PY0, PY1 = 2000, 2100  # horizontal partition faces (right room only)

EXTERIOR_LINES = [
    ((0, 0), (W, 0)),
    ((W, 0), (W, H)),
    ((W, H), (0, H)),
    ((0, H), (0, 0)),
    ((EXT, EXT), (PX0, EXT)),
    ((PX1, EXT), (W - EXT, EXT)),
    ((W - EXT, EXT), (W - EXT, PY0)),
    ((W - EXT, PY1), (W - EXT, H - EXT)),
    ((W - EXT, H - EXT), (PX1, H - EXT)),
    ((PX0, H - EXT), (EXT, H - EXT)),
    ((EXT, H - EXT), (EXT, EXT)),
]
INTERIOR_LINES = [
    ((PX0, EXT), (PX0, H - EXT)),
    ((PX1, EXT), (PX1, PY0)),
    ((PX1, PY1), (PX1, H - EXT)),
    ((PX1, PY0), (W - EXT, PY0)),
    ((PX1, PY1), (W - EXT, PY1)),
]
ROOMS = [
    [(EXT, EXT), (PX0, EXT), (PX0, H - EXT), (EXT, H - EXT)],
    [(PX1, EXT), (W - EXT, EXT), (W - EXT, PY0), (PX1, PY0)],
    [(PX1, PY1), (W - EXT, PY1), (W - EXT, H - EXT), (PX1, H - EXT)],
]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    for name in ("A-WALL-EXTR", "A-WALL-INTR", "A-FLOR"):
        doc.layers.add(name)
    msp = doc.modelspace()
    for layer, lines in (
        ("A-WALL-EXTR", EXTERIOR_LINES),
        ("A-WALL-INTR", INTERIOR_LINES),
    ):
        for a, b in lines:
            msp.add_line(a, b, dxfattribs={"layer": layer})
    for pts in ROOMS:
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-FLOR"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
