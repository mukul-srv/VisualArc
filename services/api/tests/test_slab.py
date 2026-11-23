"""The floor convention: slab and walls share a base; the finished floor is the slab top."""

from dataclasses import replace
from pathlib import Path

import ezdxf
import pytest

from api.engine.adapters.dxf.reader import read_dxf
from api.engine.canonical.model import Project, Slab
from api.engine.geometry3d.extrude import build_meshes, build_opening_parts
from api.engine.settings import DEFAULTS

NO_INFER = replace(DEFAULTS, infer_floor_boundary=False)  # the floor-without-an-outline path

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def _building(tmp_path, with_floor=True, door=False, settings=DEFAULTS):
    """4400 x 3400 outer, 200 mm walls; the 4000 x 3000 inside has A-FLOR when asked. With `door`, the
    south wall has a 900 mm gap (x 1000..1900) filled by a door marker."""
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    outer = [(0, 0), (4400, 0), (4400, 3400), (0, 3400)]
    inner = [(200, 200), (4200, 200), (4200, 3200), (200, 3200)]
    for loop in (outer, inner):
        for i, a in enumerate(loop):
            b = loop[(i + 1) % 4]
            south = a[1] == b[1] and a[1] in (0, 200)
            if door and south:
                for lo, hi in ((min(a[0], b[0]), 1000), (1900, max(a[0], b[0]))):
                    msp.add_line((lo, a[1]), (hi, a[1]), dxfattribs={"layer": "A-WALL"})
                continue
            msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    if door:
        msp.add_lwpolyline([(1000, 0), (1900, 0), (1900, 200), (1000, 200)], close=True,
                           dxfattribs={"layer": "A-DOOR"})
    if with_floor:
        msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": "A-FLOR"})
    doc.saveas(tmp_path / "c.dxf")
    return read_dxf(tmp_path / "c.dxf", 3000, ceiling_height=2600, building_type="residential", settings=settings)


def test_slab_and_walls_start_together_and_the_finished_floor_is_the_slab_top(tmp_path):
    f = _building(tmp_path).buildings[0].floors[0]
    meshes = build_meshes(f)
    (slab,) = f.slabs
    assert f.elevation.value == 0 and f.finished_level_mm == 200  # base, and base + 200 mm slab
    assert meshes[slab.id].bounds[:, 2].tolist() == [0, 200]  # the slab fills base .. finished floor
    for w in f.walls:  # walls share the base with the slab and rise to finished floor + wall height
        assert meshes[w.id].bounds[:, 2].tolist() == [0, 200 + 3000]
    assert meshes[f.boundaries[0].id].bounds[0, 2] == 200  # the walked surface
    (ceiling,) = f.ceilings
    assert ceiling.elevation.value == 200 + 2600  # finished floor + ceiling height
    (roof,) = f.roofs
    assert roof.base_elevation.value == 200 + 3000  # on the wall tops


def test_apertures_are_measured_from_the_finished_floor(tmp_path):
    f = _building(tmp_path, door=True).buildings[0].floors[0]
    (o,) = f.openings
    assert o.sill_height.value == 0
    wall = build_meshes(f)[o.wall_id]
    # the door leaf stands on the finished floor (z = 200); the wall still carries its base below
    leaf = build_opening_parts(f)[f"{o.id}-leaf"][2]
    assert leaf.bounds[0, 2] == 200 and leaf.bounds[1, 2] == pytest.approx(200 + 2100 - 50)
    assert wall.bounds[0, 2] == 0


def test_a_floor_without_a_slab_has_its_finished_floor_at_the_elevation(tmp_path):
    f = _building(tmp_path, with_floor=False, settings=NO_INFER).buildings[0].floors[0]  # no floor boundary: no slab
    assert not f.slabs and f.finished_level_mm == f.elevation.value
    assert build_meshes(f)[f.walls[0].id].bounds[:, 2].tolist() == [0, 3000]
    assert not f.ceilings


def test_floors_stack_by_their_elevations(tmp_path):
    f0 = _building(tmp_path).buildings[0].floors[0]
    up = read_dxf(tmp_path / "c.dxf", 3000, ceiling_height=2600, building_type="residential",
                  floor_elevation=3000)
    f1 = up.buildings[0].floors[0]
    assert f1.finished_level_mm - f0.finished_level_mm == 3000
    assert build_meshes(f1)[f1.slabs[0].id].bounds[:, 2].tolist() == [3000, 3200]
    assert build_meshes(f1)[f1.walls[0].id].bounds[0, 2] == 3000  # the next base sits at its elevation


def test_older_slab_shapes_still_validate():
    # 0.7.0 (no boundary_ids) and 0.7.1 (boundary_ids, holes) slabs
    base = {
        "id": "slab-001", "type": "slab", "boundary_id": "fb-001",
        "polygon": [[200, 200], [4200, 200], [4200, 3200], [200, 3200]],
        "thickness": {"value": 200, "unit": "mm", "source": "defaulted"},
        "sources": [{"format": "dxf", "layer": "A-FLOR", "entity_handle": "3C"}],
    }
    assert Slab.model_validate(base).boundary_ids == []
    assert Slab.model_validate({**base, "boundary_id": None, "boundary_ids": ["fb-001"], "holes": []}).holes == []
    legacy = (FIXTURES / "expected" / "fixture_b.canonical.json").read_text(encoding="utf-8")
    old = Project.model_validate_json(legacy.replace('"schema_version": "0.8.0"', '"schema_version": "0.7.0"'))
    assert old.schema_version == "0.7.0"  # the version is data; an older file reads fine


def test_a_space_without_a_floor_outline_is_reported(tmp_path):
    p = _building(tmp_path, with_floor=False, settings=NO_INFER)
    (issue,) = [i for i in p.issues if i.code == "slab_hole_without_floor"]
    assert issue.severity == "warning" and "A-FLOR" in issue.message
    assert not p.buildings[0].floors[0].slabs  # no outline, no slab: said, not silent
    assert "slab_hole_without_floor" not in [i.code for i in _building(tmp_path, with_floor=True).issues]


def test_floor_boundary_is_inferred_from_the_closed_wall_perimeter(tmp_path):
    p = _building(tmp_path, with_floor=False)
    f = p.buildings[0].floors[0]
    (b,) = f.boundaries  # the inside of the walls: what the drawing's own A-FLOR polygon would have been
    assert sorted(b.polygon) == sorted([(200, 200), (4200, 200), (4200, 3200), (200, 3200)])
    assert b.sources and {s.layer for s in b.sources} == {"A-WALL"}  # traceable to the walls around it
    (note,) = [i for i in p.issues if i.code == "floor_boundary_inferred"]
    assert note.severity == "warning" and "perimeter" in note.message
    (slab,) = f.slabs  # slab, finished floor and ceiling follow from it as for a drawn outline
    assert slab.boundary_id == b.id and f.finished_level_mm == 200 and f.ceilings
    assert "slab_hole_without_floor" not in [i.code for i in p.issues]
    assert "floor_boundary_inferred" not in [i.code for i in _building(tmp_path, with_floor=True).issues]


def test_open_perimeter_infers_nothing_and_says_so(tmp_path):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    for loop in ([(0, 0), (4400, 0), (4400, 3400), (0, 3400)], [(200, 200), (4200, 200), (4200, 3200), (200, 3200)]):
        for i, a in enumerate(loop[:3]):  # the west side is missing: the outline is open
            doc.modelspace().add_line(a, loop[i + 1], dxfattribs={"layer": "A-WALL"})
    doc.saveas(tmp_path / "open.dxf")
    f_p = read_dxf(tmp_path / "open.dxf", 3000, ceiling_height=2600, building_type="residential")
    assert not f_p.buildings[0].floors[0].boundaries and not f_p.buildings[0].floors[0].slabs
    (note,) = [i for i in f_p.issues if i.code == "floor_boundary_not_inferred"]
    assert note.severity == "warning" and "closed" in note.message


def test_an_unusable_floor_outline_is_not_replaced_by_an_inferred_one(tmp_path):
    # the user drew a floor outline (open, so ignored with its own warning): not overridden behind their back
    _building(tmp_path, with_floor=False)  # writes c.dxf
    doc = ezdxf.readfile(tmp_path / "c.dxf")
    doc.modelspace().add_lwpolyline([(200, 200), (4200, 200), (4200, 3200)], close=False, dxfattribs={"layer": "A-FLOR"})
    doc.saveas(tmp_path / "c2.dxf")
    p = read_dxf(tmp_path / "c2.dxf", 3000, ceiling_height=2600, building_type="residential")
    codes = [i.code for i in p.issues]
    assert "open_floor_boundary" in codes and "floor_boundary_inferred" not in codes
    assert not p.buildings[0].floors[0].boundaries
