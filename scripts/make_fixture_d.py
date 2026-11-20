"""Generate Fixture D: a scalable larger floor made of copies of Fixture Openings.

Run: cd services/api && uv run python ../../scripts/make_fixture_d.py [ROWS COLS [OUT]]
Default: 3 x 3 tiles -> fixtures/input/fixture_d.dxf (committed).

Each tile is an exact copy of fixtures/input/fixture_openings.dxf (3 rooms, 10 merged
walls, 7 openings, 3 floors, 9600 x 4000 mm), translated on a grid with 1000 mm
between tiles (more than wall_thickness_max_mm = 600, so faces of neighbouring tiles
never pair). Expected counts are therefore exactly N x the per-tile counts, which
makes the result checkable at any size. Used by scripts/benchmark.py to scale the
entity count; large sizes are generated on demand, never committed.
"""

import sys
from pathlib import Path

import ezdxf

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "fixtures" / "input" / "fixture_openings.dxf"
TILE_W, TILE_H, GAP = 9600, 4000, 1000
PER_TILE = {"walls": 10, "junctions": 8, "floor boundaries": 3, "openings": 7}


def make(rows: int, cols: int, out: Path, offset_mm: float = 0.0) -> None:
    """offset_mm shifts every tile away from the origin (coordinate-magnitude probe)."""
    src = ezdxf.readfile(SRC)
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    for layer in src.layers:
        if layer.dxf.name not in doc.layers:
            doc.layers.add(layer.dxf.name)
    msp = doc.modelspace()
    for r in range(rows):
        for c in range(cols):
            dx, dy = offset_mm + c * (TILE_W + GAP), offset_mm + r * (TILE_H + GAP)
            for e in src.modelspace():
                copy = e.copy()
                copy.translate(dx, dy, 0)
                msp.add_entity(copy)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)


if __name__ == "__main__":
    a = sys.argv[1:]
    rows, cols = (int(a[0]), int(a[1])) if len(a) >= 2 else (3, 3)
    out = Path(a[2]) if len(a) >= 3 else ROOT / "fixtures" / "input" / "fixture_d.dxf"
    make(rows, cols, out)
    print(f"wrote {out} ({rows} x {cols} tiles)")
