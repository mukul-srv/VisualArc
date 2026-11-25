"""OBJ and IFC exports (Phase 1/21): engine output re-read, and the download endpoints."""

from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import pytest
from fastapi.testclient import TestClient

from api.engine.canonical.model import Project
from api.engine.exporters.glb import build_scene
from api.engine.exporters.ifc import build_ifc
from api.engine.exporters.obj import build_obj
from api.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
NAMES = ["fixture_a", "fixture_openings", "fixture_stairs", "fixture_roofs", "fixture_columns"]


def _project(name: str) -> Project:
    return Project.model_validate_json((FIXTURES / "expected" / f"{name}.canonical.json").read_text("utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_obj_vertex_count_matches_scene(name):
    p = _project(name)
    text, _ = build_obj([(p, (0, 0))])
    assert text.strip()
    assert sum(len(g.vertices) for g in build_scene(p).geometry.values()) == sum(
        1 for ln in text.splitlines() if ln.startswith("v "))


def test_obj_offsets_shift_floors():
    p = _project("fixture_a")
    _, a = build_obj([(p, (0, 0))])
    _, b = build_obj([(p, (1000, 2000))])
    assert (b.bounds - a.bounds == [[1, 0, -2], [1, 0, -2]]).all()  # plan (x, y) -> glTF (x, -y), metres


@pytest.mark.parametrize("name", NAMES)
def test_ifc_reopens_and_counts_match_model(name):
    p = _project(name)
    data, issues = build_ifc([(p, (0, 0))])
    m = ifcopenshell.file.from_string(data.decode())
    floors = [f for b in p.buildings for f in b.floors]
    n = lambda cls: len(m.by_type(cls))
    assert n("IfcBuildingStorey") == len(floors)
    assert n("IfcWall") == sum(len(f.walls) + len(f.junctions) for f in floors)
    assert n("IfcDoor") == sum(o.kind == "door" for f in floors for o in f.openings)
    assert n("IfcWindow") == sum(o.kind == "window" for f in floors for o in f.openings)
    assert n("IfcOpeningElement") == sum(len(f.openings) for f in floors)
    assert n("IfcSpace") == sum(len(f.rooms) for f in floors)  # fixtures carry ceiling heights
    assert n("IfcColumn") == sum(c.height is not None for f in floors for c in f.columns)
    assert n("IfcStair") == sum(s.riser_count is not None for f in floors for s in f.stairs)
    assert n("IfcRoof") == sum(r.base_elevation is not None for f in floors for r in f.roofs)
    # nothing silently dropped: every unmapped element is a proxy with a recorded issue
    assert n("IfcBuildingElementProxy") == len(issues)
    assert {i["code"] for i in issues} <= {
        "ifc_surface_proxy", "ifc_balcony_flat", "ifc_no_height", "ifc_stair_no_steps", "ifc_ramp_incomplete",
        "ifc_roof_no_base", "ifc_railing_no_size", "ifc_room_no_height"}
    w = m.by_type("IfcWall")[0]
    assert w.Name and any(ps.Name == "VisualArc_Provenance" for r in w.IsDefinedBy for ps in [r.RelatingPropertyDefinition])
    # every solid is valid geometry a viewer can triangulate
    settings = ifcopenshell.geom.settings()
    for e in m.by_type("IfcElement"):
        if e.Representation and e.Representation.Representations[0].RepresentationIdentifier == "Body":
            assert ifcopenshell.geom.create_shape(settings, e).geometry.verts, e.Name


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def test_download_endpoints(client):
    up = client.post("/api/v1/uploads", params={"filename": "a.dxf"},
                     content=(FIXTURES / "input" / "fixture_openings.dxf").read_bytes()).json()["upload_id"]
    gid = client.post("/api/v1/generations", json={"upload_id": up, "wall_height": 3000, "ceiling_height": 3000}).json()["generation_id"]
    pid = client.post("/api/v1/projects/from-generation", json={"generation_id": gid, "name": "My House"}).json()["project_id"]
    for url in (f"/api/v1/generations/{gid}/export", f"/api/v1/projects/{pid}/export"):
        obj, ifc = client.get(f"{url}/obj"), client.get(f"{url}/ifc")
        assert obj.status_code == ifc.status_code == 200
        assert obj.text.count("\nv ") > 100
        assert ifcopenshell.file.from_string(ifc.text).by_type("IfcBuildingStorey")
    assert 'filename="My_House.ifc"' in client.get(f"/api/v1/projects/{pid}/export/ifc").headers["content-disposition"]
    assert client.get(f"/api/v1/projects/{pid}/export/stl").status_code == 422
    other = TestClient(app)  # another user
    assert other.get(f"/api/v1/projects/{pid}/export/ifc").status_code == 404
    assert other.get(f"/api/v1/generations/{gid}/export/obj").status_code == 404
