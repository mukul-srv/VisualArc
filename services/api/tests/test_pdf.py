"""Vector PDF input (Phase 1/24): scale suggestions, page inspection, conversion, and the confirm-first API."""

import math
from pathlib import Path

import ezdxf
import pytest
from ezdxf import bbox
from fastapi.testclient import TestClient

from api.engine.adapters.dxf.reader import InputError
from api.engine.adapters.pdf.reader import convert_pdf, inspect_pdf, is_pdf
from api.engine.adapters.pdf.scale import (
    MM_PER_PT_AT_1,
    detect_scale_candidates,
    ratio_from_two_points,
)
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
PLAN, RASTER = INPUT / "fixture_plan.pdf", INPUT / "fixture_raster.pdf"
WALLS = "PDF-000000-W100"


def _text(s, x=0.0, y=0.0):
    return {"text": s, "x": x, "y": y}


@pytest.mark.parametrize(("note", "ratio"), [
    ("SCALE 1:100", 100), ("Scale 1 : 50", 50), ("1:200", 200), ("SCALE 1/100", 100),
    ('1/4" = 1\'-0"', 48), ('1/8" = 1\'-0"', 96)])
def test_notes_give_scale_suggestions(note, ratio):
    assert [c.ratio for c in detect_scale_candidates([_text(note)], [])] == [ratio]


@pytest.mark.parametrize("note", ["Sheet 12:30", "Drawn 1:37", "A101", "1:0"])
def test_things_that_are_not_scales_are_ignored(note):
    assert detect_scale_candidates([_text(note)], []) == []  # an odd ratio needs the word "scale"


def test_dimension_text_must_agree_at_least_three_times():
    ratio = 100
    segs = [((0.0, 100.0 * i), (60.0 + 10 * i, 100.0 * i)) for i in range(4)]  # lengths 60, 70, 80, 90 pt
    texts = [_text(str(round(math.dist(a, b) * MM_PER_PT_AT_1 * ratio)), (a[0] + b[0]) / 2, a[1] + 5) for a, b in segs]
    found = detect_scale_candidates(texts, segs)
    assert len(found) == 1 and found[0].source == "dimensions" and found[0].count == 4
    assert found[0].ratio == pytest.approx(ratio, rel=0.02)
    assert detect_scale_candidates(texts[:2], segs) == []  # two dimensions are not enough to suggest anything
    skew = [*texts[:2], _text("9999", texts[2]["x"], texts[2]["y"]), _text("12345", texts[3]["x"], texts[3]["y"])]
    assert detect_scale_candidates(skew, segs) == []  # disagreeing dimensions suggest nothing


def test_two_points_make_a_scale():
    p1, p2 = (0.0, 0.0), (100.0, 0.0)
    assert ratio_from_two_points(p1, p2, 100 * MM_PER_PT_AT_1 * 50) == pytest.approx(50)
    with pytest.raises(ValueError, match="positive"):
        ratio_from_two_points(p1, p1, 1000)


def test_inspect_lists_pages_groups_and_suggestions():
    info = inspect_pdf(PLAN)
    assert [p["number"] for p in info["pages"]] == [1, 2]
    p1 = info["pages"][0]
    assert {g["layer"] for g in p1["groups"]} == {WALLS, "PDF-0000FF-W25"} and not p1["raster_only"]
    assert [c["ratio"] for c in p1["scale_candidates"]] == [100]
    assert info["pages"][1]["scale_candidates"] == []  # page 2 has no note: the user must supply one
    assert inspect_pdf(RASTER)["pages"][0]["raster_only"]
    assert is_pdf(PLAN) and not is_pdf(INPUT / "fixture_a.dxf")


def _size(msp, layer):
    ext = bbox.extents(e for e in msp if e.dxf.layer == layer)
    return ext.size.x, ext.size.y


def test_converted_plan_has_the_size_of_the_drawing_it_came_from(tmp_path):
    out = tmp_path / "plan.dxf"
    notes = convert_pdf(PLAN, out, 1, 100 * MM_PER_PT_AT_1)
    assert notes == []
    doc = ezdxf.readfile(out)
    ref = ezdxf.readfile(INPUT / "fixture_a.dxf")
    got, want = _size(doc.modelspace(), WALLS), _size(ref.modelspace(), "A-WALL")
    assert got == pytest.approx(want, abs=1.0)  # the PDF is Fixture A at 1:100, converted back at 1:100
    assert doc.header["$INSUNITS"] == 4
    assert {e.dxf.layer for e in doc.modelspace().query("TEXT")} == {"PDF-TEXT"}
    half = tmp_path / "half.dxf"
    convert_pdf(PLAN, half, 1, 50 * MM_PER_PT_AT_1)
    assert _size(ezdxf.readfile(half).modelspace(), WALLS)[0] == pytest.approx(got[0] / 2, abs=1.0)


def test_conversion_errors_are_plain(tmp_path):
    with pytest.raises(InputError, match="trace-assist"):
        convert_pdf(RASTER, tmp_path / "x.dxf", 1, 1.0)
    with pytest.raises(InputError, match="page 3"):
        convert_pdf(PLAN, tmp_path / "x.dxf", 3, 1.0)
    with pytest.raises(InputError, match="positive"):
        convert_pdf(PLAN, tmp_path / "x.dxf", 1, 0.0)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\nnot a pdf at all")
    with pytest.raises(InputError, match="not a readable PDF"):
        inspect_pdf(bad)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _upload(c, f=PLAN):
    return c.post("/api/v1/uploads", params={"filename": f.name}, content=f.read_bytes())


def test_the_scale_is_confirmed_by_the_user_before_anything_is_read(client):
    r = _upload(client)
    assert r.status_code == 201
    up = r.json()
    assert up["kind"] == "pdf" and up["needs"] == ["scale"] and len(up["pages"]) == 2
    uid = up["upload_id"]
    assert client.post("/api/v1/generations", json={"upload_id": uid, "wall_height": 3000}).status_code == 422
    url = f"/api/v1/uploads/{uid}/pdf"
    scale = {"kind": "ratio", "ratio": 100}
    assert client.post(url, json={"page": 1, "scale": scale, "confirmed": False}).status_code == 422
    assert client.post(url, json={"page": 1, "scale": scale}).status_code == 422
    assert client.post(url, json={"page": 1, "scale": {"kind": "ratio"}, "confirmed": True}).status_code == 422
    assert client.post(url, json={"page": 9, "scale": scale, "confirmed": True}).status_code == 422
    r = client.post(url, json={"page": 1, "scale": scale, "confirmed": True})
    assert r.status_code == 201, r.text
    pre = r.json()
    assert WALLS in pre["inventory"]["layers"] and pre["scale_ratio"] == 100
    # the layer-mapping step then makes it a model like any DXF
    conv = {"preset": "aia", "mapping": {WALLS: "wall", "PDF-0000FF-W25": "floor"}}
    lay = client.post(f"/api/v1/uploads/{uid}/layers", json=conv).json()
    assert {x["layer"]: x["role"] for x in lay["layers"]}[WALLS] == "wall"
    g = client.post("/api/v1/generations", json={"upload_id": uid, "wall_height": 3000, "ceiling_height": 3000,
                                                 "conventions": conv})
    assert g.status_code == 201, g.text
    canon = client.get(g.json()["artifacts"]["canonical"]).json()
    assert len(canon["buildings"][0]["floors"][0]["walls"]) >= 4
    # another page or scale can be confirmed again; the original PDF is kept
    two_pts = {"kind": "two_points", "p1": [0, 0], "p2": [100, 0], "distance_mm": 100 * MM_PER_PT_AT_1 * 50}
    again = client.post(url, json={"page": 2, "scale": two_pts, "confirmed": True})
    assert again.status_code == 201 and again.json()["scale_ratio"] == pytest.approx(50)


def test_raster_pdf_and_garbage_are_rejected_with_a_message(client):
    r = _upload(client, RASTER)
    assert r.status_code == 422 and "trace-assist" in r.json()["detail"]
    assert client.post("/api/v1/uploads", content=b"%PDF-1.4\ngarbage").status_code == 422


def test_limits_are_enforced_and_reported(monkeypatch, tmp_path):
    from api.engine.adapters.pdf import reader

    monkeypatch.setattr(reader, "MAX_PAGES", 1)
    with pytest.raises(InputError, match="2 pages, limit 1"):
        inspect_pdf(PLAN)
    monkeypatch.undo()
    monkeypatch.setattr(reader, "MAX_OBJECTS", 5)
    page = inspect_pdf(PLAN)["pages"][0]
    assert page["too_complex"] and page["groups"] == [] and page["scale_candidates"] == []  # reported, not analysed
    with pytest.raises(InputError, match="limit 5"):
        convert_pdf(PLAN, tmp_path / "x.dxf", 1, 1.0)


def test_dimension_matching_is_bounded(monkeypatch):
    from api.engine.adapters.pdf import scale

    monkeypatch.setattr(scale, "MAX_DIM_TEXTS", 2)
    monkeypatch.setattr(scale, "MAX_DIM_SEGMENTS", 2)
    segs = [((0.0, 100.0 * i), (60.0 + 10 * i, 100.0 * i)) for i in range(6)]
    texts = [_text(str(round(math.dist(a, b) * MM_PER_PT_AT_1 * 100)), (a[0] + b[0]) / 2, a[1] + 5) for a, b in segs]
    assert scale.detect_scale_candidates(texts, segs) == []  # only 2 texts x 2 segments are looked at: under the minimum


def test_library_errors_become_input_errors_not_500s(monkeypatch, tmp_path):
    from api.engine.adapters.pdf import reader

    def boom(*a, **k):
        raise RuntimeError("pdfminer exploded")

    monkeypatch.setattr(reader.pdfplumber, "open", boom)
    with pytest.raises(InputError, match="could not be read"):
        inspect_pdf(PLAN)
    with pytest.raises(InputError, match="could not be read"):
        convert_pdf(PLAN, tmp_path / "x.dxf", 1, 1.0)


def test_outlined_and_filled_shapes_are_reported(tmp_path):
    src = tmp_path / "filled.pdf"
    from importlib import util

    spec = util.spec_from_file_location("mk", INPUT.parents[1] / "scripts" / "make_fixture_pdf.py")
    mk = util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    content = b"0 0 0 RG 1 0 0 rg 1 w 100 100 200 100 re B"  # B = fill and stroke
    src.write_bytes(mk.pdf([b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>", mk.stream(content)]))
    notes = convert_pdf(src, tmp_path / "f.dxf", 1, 1.0)
    assert [n.code for n in notes] == ["pdf_fill_ignored"]
