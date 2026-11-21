"""Generate Fixtures F and F2: one DXF holding two floors (consolidated drawing, B8).

Run: cd services/api && uv run python ../../scripts/make_fixture_f.py

Both floors are a rectangular room ringed by 200 mm walls (paired lines on A-WALL,
closed LWPOLYLINE on A-FLOR), mm units, no wall/ceiling height. Outer sizes differ so
a test can tell them apart: floor 1 is W1 x H1, floor 2 is W2 x H2.
Non-floor content in both files: a roof outline on A-ROOF above the floors and a
title block (frame + TEXT on A-ANNO-TTLB) below them.

- fixture_f.dxf: floors side by side on A-WALL/A-FLOR, GAP apart (spatial split).
- fixture_f2.dxf: floors on prefixed layers `L1|A-WALL`, `L2|A-WALL`, ... drawn on top
  of each other at the origin (layer-prefix split).
"""

from pathlib import Path

import ezdxf

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input"

EXT = 200  # wall thickness
W1, H1 = 6000, 4000
W2, H2 = 5000, 3000
GAP = 8000  # clear space between the floors in fixture F (> floor_gap_mm default 5000)
FLOOR2_X = W1 + GAP  # fixture F: x of floor 2's min corner
FLOORS = [(0, 0, W1, H1), (FLOOR2_X, 0, W2, H2)]  # fixture F: (x0, y0, w, h)
RIGHT = FLOOR2_X + W2
ROOF = [(-500, H1 + 1000), (RIGHT + 500, H1 + 1000), (RIGHT + 500, H1 + 3000), (-500, H1 + 3000)]
TITLE_BLOCK = [(0, -4000), (RIGHT, -4000), (RIGHT, -2000), (0, -2000)]
TITLE_TEXT = "FLOOR PLANS 1:100"


def _floor(msp, x0, y0, w, h, wall="A-WALL", flor="A-FLOR"):
    outer = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    inner = [
        (x0 + EXT, y0 + EXT),
        (x0 + w - EXT, y0 + EXT),
        (x0 + w - EXT, y0 + h - EXT),
        (x0 + EXT, y0 + h - EXT),
    ]
    for ring in (outer, inner):
        for a, b in zip(ring, ring[1:] + ring[:1]):
            msp.add_line(a, b, dxfattribs={"layer": wall})
    msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": flor})


def _doc(layers):
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    for name in layers:
        doc.layers.add(name)
    return doc


def _non_floor(msp):
    msp.add_lwpolyline(ROOF, close=True, dxfattribs={"layer": "A-ROOF"})
    msp.add_lwpolyline(TITLE_BLOCK, close=True, dxfattribs={"layer": "A-ANNO-TTLB"})
    msp.add_text(
        TITLE_TEXT, height=300, dxfattribs={"layer": "A-ANNO-TTLB", "insert": (200, -3000)}
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = _doc(["A-WALL", "A-FLOR", "A-ROOF", "A-ANNO-TTLB"])
    for x0, y0, w, h in FLOORS:
        _floor(doc.modelspace(), x0, y0, w, h)
    _non_floor(doc.modelspace())
    doc.saveas(OUT / "fixture_f.dxf")

    layers = [f"{p}|{n}" for p in ("L1", "L2") for n in ("A-WALL", "A-FLOR")]
    doc = _doc([*layers, "A-ROOF", "A-ANNO-TTLB"])
    for p, (w, h) in (("L1", (W1, H1)), ("L2", (W2, H2))):
        _floor(doc.modelspace(), 0, 0, w, h, f"{p}|A-WALL", f"{p}|A-FLOR")
    _non_floor(doc.modelspace())
    doc.saveas(OUT / "fixture_f2.dxf")
    print(f"wrote fixture_f.dxf, fixture_f2.dxf in {OUT}")


if __name__ == "__main__":
    main()
