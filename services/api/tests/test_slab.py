"""Slab under the building part: courtyards get no slab, and 0.7.0 artifacts still validate."""

from pathlib import Path

import ezdxf
import pytest

from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import Project, Slab
from api.engine.geometry3d.extrude import build_meshes

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def _building(tmp_path, with_floor: bool):
    """4400 x 3400 outer, 200 mm walls; the 4000 x 3000 inside has A-FLOR only when asked."""
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    outer = [(0, 0), (4400, 0), (4400, 3400), (0, 3400)]
    inner = [(200, 200), (4200, 200), (4200, 3200), (200, 3200)]
    for loop in (outer, inner):
        for i, a in enumerate(loop):
            msp.add_line(a, loop[(i + 1) % 4], dxfattribs={"layer": "A-WALL"})
    if with_floor:
        msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": "A-FLOR"})
    doc.saveas(tmp_path / "c.dxf")
    return read_dxf(tmp_path / "c.dxf", 3000, ceiling_height=3000, building_type="residential")


def _top_area(mesh, z):
    up = (mesh.face_normals[:, 2] > 0.5) & (abs(mesh.triangles_center[:, 2] - z) < 1e-6)
    return mesh.area_faces[up].sum()


def test_enclosed_region_without_a_floor_boundary_gets_no_slab_and_an_issue(tmp_path):
    p = _building(tmp_path, with_floor=False)
    f = p.buildings[0].floors[0]
    (slab,) = f.slabs
    assert len(slab.holes) == 1 and slab.boundary_ids == []
    assert "slab_hole_without_floor" in [i.code for i in p.issues]
    mesh = build_meshes(f)[slab.id]
    # top face = the wall ring only: 4400 x 3400 - 4000 x 3000 mm2; nothing over the courtyard
    assert _top_area(mesh, 0) == pytest.approx(4400 * 3400 - 4000 * 3000)


def test_with_a_floor_boundary_there_is_no_hole(tmp_path):
    p = _building(tmp_path, with_floor=True)
    (slab,) = p.buildings[0].floors[0].slabs
    assert slab.holes == [] and slab.boundary_id == "fb-001"
    assert "slab_hole_without_floor" not in [i.code for i in p.issues]
    # the slab's own top faces cover the walls only: the boundary's face covers the room
    mesh = build_meshes(p.buildings[0].floors[0])[slab.id]
    assert _top_area(mesh, 0) == pytest.approx(4400 * 3400 - 4000 * 3000)


def test_a_0_7_0_slab_and_project_still_validate():
    old_slab = {
        "id": "slab-001", "type": "slab", "boundary_id": "fb-001",
        "polygon": [[200, 200], [4200, 200], [4200, 3200], [200, 3200]],
        "thickness": {"value": 200, "unit": "mm", "source": "defaulted"},
        "sources": [{"format": "dxf", "layer": "A-FLOR", "entity_handle": "3C"}],
    }
    s = Slab.model_validate(old_slab)  # no boundary_ids, no holes: both default
    assert s.boundary_id == "fb-001" and s.boundary_ids == [] and s.holes == []
    legacy = (FIXTURES / "expected" / "fixture_b.canonical.json").read_text(encoding="utf-8")
    old = Project.model_validate_json(legacy.replace('"schema_version": "0.7.1"', '"schema_version": "0.7.0"'))
    assert old.schema_version == "0.7.0"  # the version is data; a 0.7.0 file reads fine
