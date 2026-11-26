"""Generate Fixture Diagonal: one closed room with a diagonal wall, mm units, walls 200 thick.

Run: cd services/api && uv run python ../../scripts/make_fixture_diagonal.py

Wall centreline (mm), counter-clockwise: (0,0) (6000,0) (6000,3000) (4000,5000) (0,5000). The wall from
(6000,3000) to (4000,5000) is diagonal (45 deg to the axes, centreline length 2000*sqrt(2) = 2828.43).
Every wall is drawn as the two face lines on A-WALL (the mitred outer and inner offsets of the centreline);
floor = closed LWPOLYLINE on A-FLOR (the inner ring). A window marker (a rectangle turned to the diagonal
wall, on A-GLAZ) fills a gap in it from 800 to 1800 mm along the centreline (width 1000).

Hand calculation of the room (inner faces, mitred, h = 100 mm half thickness):
  area = A - P*h + h^2 * sum(cot(theta_i / 2)) with A = 28e6 mm2 (the 6000 x 5000 rectangle minus the
  2000 x 2000 corner triangle), P = 6000+3000+2000*sqrt(2)+4000+5000, interior angles 90 x3 and 135 x2.
"""

import math
from pathlib import Path

import ezdxf
from shapely.geometry import Polygon

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "fixture_diagonal.dxf"
CENTRE = [(0, 0), (6000, 0), (6000, 3000), (4000, 5000), (0, 5000)]
H = 100.0
DIAG = (CENTRE[2], CENTRE[3])
WINDOW = (800.0, 1800.0)  # along the diagonal centreline from its start


def diagonal_frame():
    (x0, y0), (x1, y1) = DIAG
    length = math.dist(DIAG[0], DIAG[1])
    u = ((x1 - x0) / length, (y1 - y0) / length)
    return (x0, y0), u, (-u[1], u[0]), length


def build(path: Path, window: bool = True) -> Path:
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    for name in ("A-WALL", "A-FLOR", "A-GLAZ"):
        doc.layers.add(name)
    msp = doc.modelspace()
    poly = Polygon(CENTRE)
    p0, u, n, _ = diagonal_frame()

    def along(q):
        return (q[0] - p0[0]) * u[0] + (q[1] - p0[1]) * u[1]

    def across(q):
        return (q[0] - p0[0]) * n[0] + (q[1] - p0[1]) * n[1]

    def at(s, t):
        return (p0[0] + s * u[0] + t * n[0], p0[1] + s * u[1] + t * n[1])

    for ring in (poly.buffer(H, join_style="mitre").exterior, poly.buffer(-H, join_style="mitre").exterior):
        pts = list(ring.coords)[:-1]
        for a, b in zip(pts, pts[1:] + pts[:1], strict=True):
            if window and abs(across(a) - across(b)) < 1e-6 and abs(abs(across(a)) - H) < 1e-6:  # a face of the diagonal wall
                t, (s0, s1) = math.copysign(H, across(a)), sorted((along(a), along(b)))
                for lo, hi in ((s0, WINDOW[0]), (WINDOW[1], s1)):  # the stretch between the window bounds is the gap
                    msp.add_line(at(lo, t), at(hi, t), dxfattribs={"layer": "A-WALL"})
            else:
                msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    inner = list(poly.buffer(-H, join_style="mitre").exterior.coords)[:-1]
    msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": "A-FLOR"})
    if window:
        s0, s1 = WINDOW
        quad = [at(s, t) for s, t in ((s0, -H), (s1, -H), (s1, H), (s0, H))]
        msp.add_lwpolyline(quad, close=True, dxfattribs={"layer": "A-GLAZ"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


if __name__ == "__main__":
    print(f"wrote {build(OUT)}")
