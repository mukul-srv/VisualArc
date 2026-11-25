"""Generate Fixture Interpret: one room exercising the 26a interpretation rules, mm units.

Run: cd services/api && uv run python ../../scripts/make_fixture_interpret.py

Plan (mm), walls 200 thick: outer face (0,0)-(6400,4400); clear room (200,200)-(6200,4200).
  bottom wall   both faces broken by a 20 mm gap at x 3000..3020  -> healed (limit 30 mm)
  top wall      both faces broken by a 200 mm gap at x 2000..2200 -> off tolerance, stays reported
  right wall    both faces broken at y 1500..2400 (900 mm), block DOOR_900 (leaf line + quarter arc)
                inserted at its corner -> recognised door; the opening comes from the wall gap
  bottom wall   block WIN_1200 (3 parallel lines 1200 long, 100 apart) at x 4400..5600 -> window marker
  room          block STAIR_RUN (6 parallel lines, 250 apart) -> recognised stair outline (no arrow:
                direction missing is reported); block STAIR_NOTE (name only) -> ambiguous
  (anon=True adds block XQ7: window lines, no name hint, across the left wall, rotated 90)
  DIMENSION     linear 6000 between the clear faces, text `dim_text` (default "6000" = consistent)
All blocks are inserted on layer BLOCKS (not an opening layer), floor = closed LWPOLYLINE on A-FLOR.
"""

from pathlib import Path

import ezdxf

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "fixture_interpret.dxf"


def build(path: Path, dim_text: str = "6000", blocks: bool = True, units=ezdxf.units.MM, anon: bool = False) -> Path:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = units
    for name in ("A-WALL", "A-FLOR", "BLOCKS", "A-ANNO-DIMS"):
        doc.layers.add(name)
    msp = doc.modelspace()
    wall = {"layer": "A-WALL"}

    def line(a, b):
        msp.add_line(a, b, dxfattribs=wall)

    line((0, 0), (3000, 0)); line((3020, 0), (6400, 0))  # bottom outer, 20 mm gap
    line((200, 200), (3000, 200)); line((3020, 200), (6200, 200))
    line((6400, 0), (6400, 1500)); line((6400, 2400), (6400, 4400))  # right, 900 mm gap
    line((6200, 200), (6200, 1500)); line((6200, 2400), (6200, 4200))
    line((6400, 4400), (2200, 4400)); line((2000, 4400), (0, 4400))  # top, 200 mm gap
    line((6200, 4200), (2200, 4200)); line((2000, 4200), (200, 4200))
    line((0, 4400), (0, 0)); line((200, 4200), (200, 200))
    msp.add_lwpolyline([(200, 200), (6200, 200), (6200, 4200), (200, 4200)], close=True, dxfattribs={"layer": "A-FLOR"})
    msp.add_linear_dim(base=(0, -500), p1=(200, 200), p2=(6200, 200), text=dim_text,
                       dxfattribs={"layer": "A-ANNO-DIMS"}).render()
    if blocks:
        door = doc.blocks.new("DOOR_900")
        door.add_line((0, 0), (900, 0)); door.add_arc((0, 0), 900, 0, 90)
        win = doc.blocks.new("WIN_1200")
        for y in (0, 100, 200):
            win.add_line((0, y), (1200, y))
        stair = doc.blocks.new("STAIR_RUN")
        for i in range(6):
            stair.add_line((0, 250 * i), (1000, 250 * i))
        doc.blocks.new("STAIR_NOTE").add_line((0, 0), (300, 300))
        at = {"layer": "BLOCKS"}
        msp.add_blockref("DOOR_900", (6400, 1500), dxfattribs={**at, "rotation": 90})
        msp.add_blockref("WIN_1200", (4400, 0), dxfattribs=at)
        msp.add_blockref("STAIR_RUN", (500, 700), dxfattribs=at)
        msp.add_blockref("STAIR_NOTE", (3000, 2500), dxfattribs=at)
    if blocks and anon:  # a window symbol whose name says nothing, across the left wall (geometry only)
        anon_win = doc.blocks.new("XQ7")
        for y in (0, 100, 200):
            anon_win.add_line((0, y), (1200, y))
        msp.add_blockref("XQ7", (200, 1500), dxfattribs={"layer": "BLOCKS", "rotation": 90})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


if __name__ == "__main__":
    print(f"wrote {build(OUT)}")
