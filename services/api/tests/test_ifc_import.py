"""IFC import (Phase 1/22): round trip through the IFC exporter, issues for what is not mapped, upload flow."""

from pathlib import Path

import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import pytest
from fastapi.testclient import TestClient

from api.engine.adapters.ifc.reader import is_ifc, read_ifc
from api.engine.canonical.model import Measured, Project
from api.engine.exporters.glb import build_scene
from api.engine.exporters.ifc import build_ifc
from api.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
NAMES = ["fixture_a", "fixture_openings", "fixture_stairs", "fixture_roofs", "fixture_columns"]
TOL = 0.01  # mm


def _project(name: str) -> Project:
    return Project.model_validate_json((FIXTURES / "expected" / f"{name}.canonical.json").read_text("utf-8"))


def _roundtrip(p: Project, tmp_path: Path) -> Project:
    path = tmp_path / "rt.ifc"
    path.write_bytes(build_ifc([(p, (0, 0))])[0])
    return read_ifc(path)


def _close(a: list, b: list) -> bool:
    return len(a) == len(b) and all(x == pytest.approx(y, abs=TOL) for x, y in zip(sorted(a), sorted(b), strict=True))


def _wall_dims(f):
    """(length, thickness, height) per wall, junctions as the squares they are (the IFC has IfcWall for both)."""
    out = [(w.centreline.end[0] - w.centreline.start[0] + w.centreline.end[1] - w.centreline.start[1],
            w.thickness.value, w.height.value) for w in f.walls]
    for j in f.junctions:
        xs, ys = [p[0] for p in j.polygon], [p[1] for p in j.polygon]
        h = max(w.height.value for w in f.walls if w.id in j.wall_ids)
        long, short = sorted((max(xs) - min(xs), max(ys) - min(ys)), reverse=True)
        out.append((long, short, h))
    return sorted(out)


@pytest.mark.parametrize("name", NAMES)
def test_round_trip_counts_and_dimensions(name, tmp_path):
    p = _project(name)
    f0 = p.buildings[0].floors[0]
    q = _roundtrip(p, tmp_path)
    f1 = q.buildings[0].floors[0]
    assert not [i for i in q.issues if i.severity == "blocking"]
    assert f1.elevation.value == pytest.approx(f0.elevation.value) and f1.elevation.source == "source_extracted"
    assert f1.finished_level_mm == pytest.approx(f0.finished_level_mm)
    got = sorted((max(abs(w.centreline.end[0] - w.centreline.start[0]), abs(w.centreline.end[1] - w.centreline.start[1])),
                  w.thickness.value, w.height.value) for w in f1.walls)
    want = _wall_dims(f0)
    assert len(got) == len(want)
    for g, w in zip(got, sorted((abs(a), b, c) for a, b, c in want), strict=True):
        assert g == pytest.approx(w, abs=TOL)
    key = lambda o: (o.kind, round(o.width.value), round(o.height.value), round(o.sill_height.value))
    assert sorted(map(key, f1.openings)) == sorted(map(key, f0.openings))
    assert _close([r.area.value for r in f1.rooms], [r.area.value for r in f0.rooms])
    assert sorted(r.name for r in f1.rooms) == sorted(r.name for r in f0.rooms)
    assert _close([s.thickness.value for s in f1.slabs], [s.thickness.value for s in f0.slabs + f0.balconies if s.thickness])
    assert _close([c.height.value for c in f1.columns], [c.height.value for c in f0.columns])
    assert sorted(c.shape for c in f1.columns) == sorted(c.shape for c in f0.columns)
    assert [(s.riser_count, s.direction) for s in f1.stairs] == [(s.riser_count, s.direction) for s in f0.stairs
                                                                  if s.riser_count]
    for a, b in zip(f1.stairs, [s for s in f0.stairs if s.riser_count], strict=False):
        assert a.riser_height.value == pytest.approx(b.riser_height.value, abs=TOL)
        assert a.tread_depth.value == pytest.approx(b.tread_depth.value, abs=TOL)
    assert [r.kind for r in f1.roofs] == [r.kind for r in f0.roofs]
    for a, b in zip(f1.roofs, f0.roofs, strict=True):
        assert a.base_elevation.value == pytest.approx(b.base_elevation.value, abs=TOL)
        if b.kind != "flat":
            assert a.ridge_height.value == pytest.approx(b.ridge_height.value, abs=TOL)
            assert a.ridge_axis == b.ridge_axis


def test_provenance_and_the_imported_model_builds(tmp_path):
    q = _roundtrip(_project("fixture_openings"), tmp_path)
    f = q.buildings[0].floors[0]
    assert all(s.format == "ifc" and s.layer.startswith("Ifc") and len(s.entity_handle) == 22
               for w in f.walls for s in w.sources)
    assert {w.thickness.source for w in f.walls} == {"source_extracted"}
    assert {o.detail.frame_width.source for o in f.openings if o.detail} == {"defaulted"}  # nominal, never in an IFC
    assert all(r.name_source == "source_extracted" for r in f.rooms)
    assert build_scene(q).geometry  # the GLB pipeline takes it


def test_unmapped_entities_are_issues_not_silence(tmp_path):
    """The exporter's footprint-only proxies (boundary, ceiling) come back as one recorded issue per type."""
    q = _roundtrip(_project("fixture_columns"), tmp_path)
    issues = [i for i in q.issues if i.code == "ifc_unsupported_entity"]
    assert issues and issues[0].sources and all(s.format == "ifc" for s in issues[0].sources)
    assert "IfcBuildingElementProxy" in " ".join(i.message for i in issues)


def _bare(tmp_path, units=True, storey=True, beam=False) -> Path:
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    if units:
        ifcopenshell.api.unit.assign_unit(f)
    if storey:
        st = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="G")
        st.Elevation = 0.0
        if beam:
            b = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBeam", name="b")
            ifcopenshell.api.spatial.assign_container(f, products=[b], relating_structure=st)
    path = tmp_path / "bare.ifc"
    f.write(str(path))
    return path


def test_blocking_and_unsupported_cases(tmp_path):
    assert [i.code for i in read_ifc(_bare(tmp_path, units=False)).issues] == ["ifc_units_missing"]
    assert [i.code for i in read_ifc(_bare(tmp_path, storey=False)).issues] == ["ifc_no_storeys"]
    q = read_ifc(_bare(tmp_path, beam=True))
    assert {i.code for i in q.issues} >= {"ifc_unsupported_entity"}
    assert not is_ifc(FIXTURES / "input" / "fixture_a.dxf") and is_ifc(_bare(tmp_path))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _two_storeys() -> bytes:
    p = _project("fixture_openings")
    f = p.buildings[0].floors[0]
    up = f.model_copy(update={"id": "floor-1", "name": "Upper", "elevation": Measured(value=3200, source="user_provided")})
    return build_ifc([(p.model_copy(update={"buildings": [p.buildings[0].model_copy(update={"floors": [f, up]})]}), (0, 0))])[0]


def test_upload_and_import_flow(client):
    r = client.post("/api/v1/uploads", params={"filename": "house.ifc"}, content=_two_storeys())
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "ifc" and [s["elevation"] for s in body["storeys"]] == [0.0, 3200.0] and body["floor_candidates"] == []
    r = client.post(f"/api/v1/uploads/{body['upload_id']}/ifc", json={"project_name": "From IFC"})
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    m = client.get(f"/api/v1/projects/{pid}").json()
    assert [f["elevation"]["value"] for f in m["floors"]] == [0.0, 3200.0]
    for f in m["floors"]:
        assert client.get(f"/api/v1/generations/{f['generation_id']}/artifacts/glb").status_code == 200
        canon = client.get(f"/api/v1/generations/{f['generation_id']}/artifacts/canonical").json()
        assert canon["buildings"][0]["floors"][0]["walls"][0]["sources"][0]["format"] == "ifc"
    # IFC floors are not DXF floors: no edits, and the export round-trips
    assert client.get(f"/api/v1/projects/{pid}/export/ifc").status_code == 200
    # the whole file as one standalone model also works through the normal generation call
    g = client.post("/api/v1/generations", json={"upload_id": body["upload_id"]})
    assert g.status_code == 201 and len(client.get(g.json()["artifacts"]["canonical"]).json()["buildings"][0]["floors"]) == 2


def test_ifc_upload_rejects_garbage_and_blocked(client, tmp_path):
    assert client.post("/api/v1/uploads", content=b"ISO-10303-21;\nnot really\n").status_code == 422
    up = client.post("/api/v1/uploads", content=_bare(tmp_path, units=False).read_bytes()).json()
    assert up["storeys"] == [] and up["issues"][0]["code"] == "ifc_units_missing"
    r = client.post(f"/api/v1/uploads/{up['upload_id']}/ifc", json={"project_name": "x"})
    assert r.status_code == 409 and r.json()["issues"][0]["severity"] == "blocking"
