import dataclasses
import importlib.util
from pathlib import Path

import ezdxf

from api.engine.adapters.dxf.reader import read_dxf
from api.engine.exporters.glb import build_meta, build_scene

ROOT = Path(__file__).resolve().parents[3]
INPUT = ROOT / "fixtures" / "input"


def _gen(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _walls(p):
    return p.buildings[0].floors[0].walls


def _on_perimeter(w, width, height, ext):
    """Oracle from generator constants: centreline runs along the building edge."""
    (x0, y0), (_x1, y1) = w.centreline.start, w.centreline.end
    if y0 == y1:
        return y0 in (ext / 2, height - ext / 2)
    return x0 in (ext / 2, width - ext / 2)


def _codes(p, code):
    return [i for i in p.issues if i.code == code]


def test_layer_roles_fixture_g():
    g = _gen("make_fixture_g")
    p = read_dxf(INPUT / "fixture_g.dxf", 3000, ceiling_height=3000)
    assert not [i for i in p.issues if i.severity == "blocking"]
    assert not _codes(p, "wall_role_inferred")
    for w in _walls(p):
        assert w.role_source == "source_extracted"
        assert w.role == (
            "exterior" if _on_perimeter(w, g.W, g.H, g.EXT) else "interior"
        )
    assert {w.role for w in _walls(p)} == {"exterior", "interior"}


def test_inference_fixture_a_perimeter_exterior_partition_interior():
    a = _gen("make_fixture_a")
    p = read_dxf(INPUT / "fixture_a.dxf", 3000, ceiling_height=3000)
    walls = _walls(p)
    assert {w.role_source for w in walls} == {"inferred"}
    for w in walls:
        assert w.role == (
            "exterior" if _on_perimeter(w, a.W, a.H, a.EXT) else "interior"
        )
    assert [w.role for w in walls].count("interior") == 1
    (warn,) = _codes(p, "wall_role_inferred")
    assert warn.severity == "warning"
    assert {s.entity_handle for s in warn.sources} == {
        s.entity_handle for w in walls for s in w.sources
    }


def test_inference_fixture_b_all_exterior():
    p = read_dxf(INPUT / "fixture_b.dxf", 3000, ceiling_height=3000)
    assert {w.role for w in _walls(p)} == {"exterior"}


def test_inference_on_fixture_g_geometry_when_layers_flattened(tmp_path):
    _gen("make_fixture_g")
    doc = ezdxf.readfile(INPUT / "fixture_g.dxf")
    for e in doc.modelspace().query("LINE"):
        e.dxf.layer = "A-WALL"
    path = tmp_path / "flat.dxf"
    doc.saveas(path)
    p = read_dxf(path, 3000, ceiling_height=3000)
    layered = {w.id: w.role for w in _walls(read_dxf(INPUT / "fixture_g.dxf", 3000, ceiling_height=3000))}
    assert {w.id: w.role for w in _walls(p)} == layered
    assert {w.role_source for w in _walls(p)} == {"inferred"}
    assert len(_codes(p, "wall_role_inferred")) == 1


def test_mixed_layered_and_plain_walls_warns_only_for_plain(tmp_path):
    doc = ezdxf.readfile(INPUT / "fixture_g.dxf")
    for e in doc.modelspace().query("LINE"):
        if e.dxf.layer == "A-WALL-INTR":
            e.dxf.layer = "A-WALL"
    path = tmp_path / "mixed.dxf"
    doc.saveas(path)
    p = read_dxf(path, 3000, ceiling_height=3000)
    by = {w.role_source for w in _walls(p)}
    assert by == {"source_extracted", "inferred"}
    (warn,) = _codes(p, "wall_role_inferred")
    inferred = {s.entity_handle for w in _walls(p) if w.role_source == "inferred" for s in w.sources}
    assert {s.entity_handle for s in warn.sources} == inferred


def test_conflicting_role_layers_block_and_cite_both_sources(tmp_path):
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    a = msp.add_line((0, 0), (3000, 0), dxfattribs={"layer": "A-WALL-EXTR"})
    b = msp.add_line((0, 200), (3000, 200), dxfattribs={"layer": "A-WALL-INTR"})
    path = tmp_path / "c.dxf"
    doc.saveas(path)
    p = read_dxf(path, 3000, ceiling_height=3000)
    (issue,) = _codes(p, "wall_role_conflict")
    assert issue.severity == "blocking"
    assert {s.entity_handle for s in issue.sources} == {a.dxf.handle, b.dxf.handle}
    assert {s.layer for s in issue.sources} == {"A-WALL-EXTR", "A-WALL-INTR"}
    (w,) = _walls(p)
    assert (w.role, w.role_source) == (None, None)


def test_role_layer_mapping_is_configurable(tmp_path):
    from api.engine.settings import Settings

    s = dataclasses.replace(
        Settings(), wall_role_layers=(("MY-OUT", "exterior"), ("MY-IN", "interior"))
    )
    doc = ezdxf.readfile(INPUT / "fixture_g.dxf")
    for e in doc.modelspace().query("LINE"):
        e.dxf.layer = "MY-OUT" if e.dxf.layer == "A-WALL-EXTR" else "MY-IN"
    path = tmp_path / "m.dxf"
    doc.saveas(path)
    p = read_dxf(path, 3000, ceiling_height=3000, settings=s)
    assert {w.role_source for w in _walls(p)} == {"source_extracted"}
    assert {w.role for w in _walls(p)} == {"exterior", "interior"}


def test_role_reaches_glb_metadata_and_meta():
    p = read_dxf(INPUT / "fixture_g.dxf", 3000, ceiling_height=3000)
    scene = build_scene(p)
    meta = build_meta(p, scene)
    for w in _walls(p):
        m = scene.geometry[w.id].metadata
        assert (m["role"], m["role_source"]) == (w.role, w.role_source)
        assert meta["elements"][w.id]["role"] == w.role
