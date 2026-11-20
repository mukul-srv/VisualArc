"""Generate synthetic Fixture Openings: three rooms in a row with doors and windows (ADR-002), mm.

Run: cd services/api && uv run python ../../scripts/make_fixture_openings.py

Plan (mm, $INSUNITS = 4). Exterior walls 200 thick, interior walls 100 thick. No wall height.
  outer face   (0,0)-(9600,4000)
  room 1 clear (200,200)-(3200,3800)     3000 x 3600
  interior wall 1: x 3200..3300  (centreline x=3250)
  room 2 clear (3300,200)-(6300,3800)    3000 x 3600
  interior wall 2: x 6300..6400  (centreline x=6350)
  room 3 clear (6400,200)-(9400,3800)    3000 x 3600
Walls = paired face lines on A-WALL, broken at every gap. Floors = closed LWPOLYLINE on A-FLOR.
Openings (ADR-002 option B): closed 4-vertex axis-aligned LWPOLYLINE exactly filling the gap on
A-DOOR (doors) / A-GLAZ (windows). Jamb LINEs on A-WALL at the gap ends only where noted.
Decorative swing ARC + leaf LINE on A-DOOR for D1-D3 (ARC centre = marker vertex = hinge).

Expected openings (id order = sorted by span start (y, x)). Span is on the host centreline;
offset = distance from host centreline start (lower x / lower y end) to span start, AFTER merging.
  id           kind    host (merged, see below)  span (centreline)         offset width jambs
  opening-001  window  B1 bottom ext 1           (1200,100)-(1700,100)       1000   500  yes (50-600 case)
  opening-002  window  B2 bottom ext 2           (4400,100)-(5600,100)       1100  1200  no
  opening-003  door    B3 bottom ext 3           (7500,100)-(8400,100)       1100   900  no
  opening-004  door    I1 interior 1             (3250,1000)-(3250,1900)      800   900  yes
  opening-005  window  L  left ext               (100,1500)-(100,2400)       1300   900  no
  opening-006  window  R  right ext              (9500,1500)-(9500,2700)     1300  1200  yes
  opening-007  door    I2 interior 2             (6350,2000)-(6350,2800)     1800   800  no
Rooms: R1 {001,004,005}, R2 {002,004,007}, R3 {003,006,007}. Door 004 joins R1-R2, 007 joins R2-R3.
Defaults expected (not in DXF): door h2100/sill0, window h1200/sill900.

Expected merged walls (10; thickness in brackets; centrelines exclude junction fill, so exterior
horizontal walls are split at the interior walls and vertical walls start/end at y=200/3800):
  B1 (200,100)-(3200,100) [200]   B2 (3300,100)-(6300,100) [200]   B3 (6400,100)-(9400,100) [200]
  T1 (200,3900)-(3200,3900) [200] T2 (3300,3900)-(6300,3900) [200] T3 (6400,3900)-(9400,3900) [200]
  L  (100,200)-(100,3800) [200]   I1 (3250,200)-(3250,3800) [100]
  I2 (6350,200)-(6350,3800) [100] R  (9500,200)-(9500,3800) [200]
Wall ids are not listed: they follow the reader's sort after merging (T11).
"""

from pathlib import Path

import ezdxf

OUT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "input" / "fixture_openings.dxf"
)

W, H, EXT = 9600, 4000, 200
INT1 = (3200, 3300)  # interior wall 1 faces (x)
INT2 = (6300, 6400)  # interior wall 2 faces (x)
# (id, kind, axis, c0, c1, a0, a1, jambs); axis "h": gap along x on a wall spanning y c0..c1.
OPENINGS = [
    ("opening-001", "window", "h", 0, 200, 1200, 1700, True),
    ("opening-002", "window", "h", 0, 200, 4400, 5600, False),
    ("opening-003", "door", "h", 0, 200, 7500, 8400, False),
    ("opening-004", "door", "v", 3200, 3300, 1000, 1900, True),
    ("opening-005", "window", "v", 0, 200, 1500, 2400, False),
    ("opening-006", "window", "v", 9400, 9600, 1500, 2700, True),
    ("opening-007", "door", "v", 6300, 6400, 2000, 2800, False),
]
# Decorative swings: (centre, radius, start deg, end deg, leaf end).
SWINGS = [
    ((3200, 1000), 900, 0, 90, (4100, 1000)),
    ((6400, 2000), 800, 90, 180, (5600, 2000)),
    ((7500, 200), 900, 0, 90, (7500, 1100)),
]


def cut(a0, a1, holes):
    """Split [a0, a1] at holes, returning the remaining intervals."""
    out, p = [], a0
    for h0, h1 in sorted(holes):
        if h0 > p:
            out.append((p, h0))
        p = h1
    if p < a1:
        out.append((p, a1))
    return out


def face_lines():
    lines = []
    # horizontal faces: y, x pieces, gap-bearing openings are those whose wall covers y
    for y, pieces in (
        (0, [(0, W)]),
        (EXT, [(EXT, INT1[0]), (INT1[1], INT2[0]), (INT2[1], W - EXT)]),
        (H - EXT, [(EXT, INT1[0]), (INT1[1], INT2[0]), (INT2[1], W - EXT)]),
        (H, [(0, W)]),
    ):
        holes = [(o[5], o[6]) for o in OPENINGS if o[2] == "h" and y in (0, EXT)]
        for p0, p1 in pieces:
            for s0, s1 in cut(p0, p1, [h for h in holes if p0 <= h[0] and h[1] <= p1]):
                lines.append(((s0, y), (s1, y)))
    # vertical faces: x, y range, holes from the openings on that wall
    for x, (y0, y1) in (
        (0, (0, H)),
        (EXT, (EXT, H - EXT)),
        (W - EXT, (EXT, H - EXT)),
        (W, (0, H)),
        (INT1[0], (EXT, H - EXT)),
        (INT1[1], (EXT, H - EXT)),
        (INT2[0], (EXT, H - EXT)),
        (INT2[1], (EXT, H - EXT)),
    ):
        holes = [(o[5], o[6]) for o in OPENINGS if o[2] == "v" and x in (o[3], o[4])]
        for s0, s1 in cut(y0, y1, holes):
            lines.append(((x, s0), (x, s1)))
    return lines


def rect(o):
    _, _, axis, c0, c1, a0, a1, _ = o
    if axis == "h":
        return [(a0, c0), (a1, c0), (a1, c1), (a0, c1)]
    return [(c0, a0), (c1, a0), (c1, a1), (c0, a1)]


def main() -> None:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM  # $INSUNITS = 4
    for name in ("A-WALL", "A-FLOR", "A-DOOR", "A-GLAZ"):
        doc.layers.add(name)
    msp = doc.modelspace()
    wall = {"layer": "A-WALL"}
    for a, b in face_lines():
        msp.add_line(a, b, dxfattribs=wall)
    for o in OPENINGS:
        layer = "A-DOOR" if o[1] == "door" else "A-GLAZ"
        pts = rect(o)
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
        if o[7]:  # jambs: the two marker edges perpendicular to the wall axis
            i, j, k, m = (0, 3, 1, 2) if o[2] == "h" else (0, 1, 3, 2)
            msp.add_line(pts[i], pts[j], dxfattribs=wall)
            msp.add_line(pts[k], pts[m], dxfattribs=wall)
    for c, r, s, e, leaf in SWINGS:
        msp.add_arc(c, r, s, e, dxfattribs={"layer": "A-DOOR"})
        msp.add_line(c, leaf, dxfattribs={"layer": "A-DOOR"})
    for x0, x1 in ((EXT, INT1[0]), (INT1[1], INT2[0]), (INT2[1], W - EXT)):
        pts = [(x0, EXT), (x1, EXT), (x1, H - EXT), (x0, H - EXT)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-FLOR"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
