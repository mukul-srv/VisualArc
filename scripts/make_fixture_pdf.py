"""Generate the vector-PDF fixtures: fixture_plan.pdf (Fixture A drawn at 1:100, two pages) and
fixture_raster.pdf (a scan: one image, no vector paths). No dependency: the PDF is written by hand.

Run: cd services/api && uv run python ../../scripts/make_fixture_pdf.py

Page 1 = Fixture A: walls are black 1 pt lines, floors thin blue closed polylines, a "SCALE 1:100" note and
the overall dimensions as text ("8200", "5200"). Page 2 = a bare 3000 x 2000 mm rectangle with no scale note.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_fixture_a import H, ROOMS, W, WALL_LINES  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "input"
PT_PER_MM = 72 / 25.4 / 100  # 1:100 on paper
MARGIN = 40.0


def pdf(objs: list[bytes]) -> bytes:
    """objs[i] is object i + 1 (1 = catalog); writes header, objects, xref, trailer."""
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def stream(data: bytes, extra: str = "") -> bytes:
    return f"<< /Length {len(data)} {extra}>>\nstream\n".encode() + data + b"\nendstream"


def pt(v: float) -> float:
    return MARGIN + v * PT_PER_MM


def plan_page() -> bytes:
    c = ["0 0 0 RG 1 w"]
    for (x0, y0), (x1, y1) in WALL_LINES:
        c.append(f"{pt(x0):.3f} {pt(y0):.3f} m {pt(x1):.3f} {pt(y1):.3f} l S")
    c.append("0 0 1 RG 0.25 w")
    for ring in ROOMS:
        c.append(" ".join(f"{pt(x):.3f} {pt(y):.3f} {'m' if i == 0 else 'l'}" for i, (x, y) in enumerate(ring)) + " h S")
    c.append("BT /F1 10 Tf 0 0 0 rg")
    for x, y, s in ((pt(0), pt(-1200), "SCALE 1:100"), (pt(W / 2 - 400), pt(-300), "8200"), (pt(W + 300), pt(H / 2), "5200")):
        c.append(f"1 0 0 1 {x:.3f} {y:.3f} Tm ({s}) Tj")
    c.append("ET")
    return "\n".join(c).encode()


def second_page() -> bytes:
    return f"0 0 0 RG 1 w {pt(0):.3f} {pt(0):.3f} {3000 * PT_PER_MM:.3f} {2000 * PT_PER_MM:.3f} re S".encode()


def vector_pdf() -> bytes:
    page = lambda n: f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {n} 0 R /Resources << /Font << /F1 3 0 R >> >> >>".encode()  # noqa: E731
    return pdf([b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [5 0 R 7 0 R] /Count 2 >>",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", stream(plan_page()), page(4),
                stream(second_page()), page(6)])


def raster_pdf() -> bytes:
    img = stream(bytes([0, 255, 255, 0]), "/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8 ")
    return pdf([b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>",
                stream(b"q 400 0 0 400 50 200 cm /Im1 Do Q"), img])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fixture_plan.pdf").write_bytes(vector_pdf())
    (OUT / "fixture_raster.pdf").write_bytes(raster_pdf())
    print(f"wrote {OUT / 'fixture_plan.pdf'} and fixture_raster.pdf")
