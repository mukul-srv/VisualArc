import dataclasses
from pathlib import Path

import ezdxf
import pytest

from api.engine.adapters.dxf.reader import InputError, read_dxf
from api.engine.geometry2d.walls import Segment, pair_walls
from api.engine.settings import DEFAULTS, Settings


def test_defaults_match_document_08():
    # changing a default is a convention change: update Document 08 + ADR-003 too
    assert dataclasses.asdict(DEFAULTS) == {
        "wall_layer": "A-WALL",
        "floor_layer": "A-FLOR",
        "door_layer": "A-DOOR",
        "window_layer": "A-GLAZ",
        "default_door_height_mm": 2100.0,
        "default_door_sill_mm": 0.0,
        "default_window_height_mm": 1200.0,
        "default_window_sill_mm": 900.0,
        "wall_thickness_min_mm": 50.0,
        "wall_thickness_max_mm": 600.0,
        "tolerance_mm": 1e-6,
        "extrusion_tolerance": 1e-6,
        "max_dxf_bytes": 5 * 2**20,
        "max_entities": 5000,
        "max_wall_segments": 600,
        "max_opening_markers": 120,
        "unmapped_ref_cap": 20,
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULTS.tolerance_mm = 1.0


@pytest.mark.parametrize(
    "bad",
    [
        {"default_door_height_mm": 0},
        {"default_window_height_mm": -1},
        {"default_door_sill_mm": -1},
        {"default_window_sill_mm": -0.5},
    ],
)
def test_invalid_opening_defaults_rejected(bad):
    with pytest.raises(ValueError):
        Settings(**bad)


def _wall(thickness, dy=0.0):
    return [
        Segment("H0", "A-WALL", (0, 0), (1000, 0)),
        Segment("H1", "A-WALL", (0, thickness), (1000, thickness + dy)),
    ]


@pytest.mark.parametrize(
    "thickness, widened",
    [
        (700, Settings(wall_thickness_max_mm=800)),
        (30, Settings(wall_thickness_min_mm=20)),
    ],
)
def test_thickness_range_is_configurable(thickness, widened):
    walls, issues = pair_walls(_wall(thickness))
    assert walls == [] and {i.code for i in issues} == {"unpaired_segment"}
    (w,), issues = pair_walls(_wall(thickness), widened)
    assert w.thickness == pytest.approx(thickness) and issues == []


def test_tolerance_is_configurable():
    # a 0.01 mm drafting error is NOT absorbed by the default 1e-6 mm tolerance
    walls, issues = pair_walls(_wall(200, dy=0.01))
    assert walls == [] and "non_orthogonal_segment" in {i.code for i in issues}
    walls, issues = pair_walls(_wall(200, dy=0.01), Settings(tolerance_mm=0.1))
    assert len(walls) == 1 and issues == []


def _dxf(tmp_path: Path, wall_layer: str, notes: int = 0) -> Path:
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in [((0, 0), (1000, 0)), ((0, 200), (1000, 200))]:
        msp.add_line(a, b, dxfattribs={"layer": wall_layer})
    for _ in range(notes):
        msp.add_line((0, 900), (10, 900), dxfattribs={"layer": "NOTES"})
    path = tmp_path / "t.dxf"
    doc.saveas(path)
    return path


def test_reader_uses_settings_layers_and_ref_cap(tmp_path: Path):
    path = _dxf(tmp_path, "s-wall", notes=3)
    assert "no_walls" in [i.code for i in read_dxf(path, 3000).issues]
    p = read_dxf(path, 3000, settings=Settings(wall_layer="S-WALL", unmapped_ref_cap=2))
    assert len(p.buildings[0].floors[0].walls) == 1  # layer match is case-insensitive
    (notes,) = [i for i in p.issues if i.code == "unmapped_layer"]
    assert len(notes.sources) == 2 and "first 2 of 3" in notes.message


def test_reader_size_limit_from_settings(tmp_path: Path):
    path = _dxf(tmp_path, "A-WALL")
    with pytest.raises(InputError):
        read_dxf(path, 3000, settings=Settings(max_dxf_bytes=100))
    # explicit max_bytes (the CLI --max-mb path) still overrides settings
    assert read_dxf(path, 3000, max_bytes=10**9, settings=Settings(max_dxf_bytes=100))


def test_extrusion_tolerance_is_configurable(tmp_path: Path):
    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 4
    doc.modelspace().add_lwpolyline(
        [(0, 0), (1000, 0), (1000, 1000)],
        close=True,
        dxfattribs={"layer": "A-FLOR", "extrusion": (1e-4, 0, 1)},
    )
    path = tmp_path / "tilt.dxf"
    doc.saveas(path)
    codes = lambda p: [i.code for i in p.issues]
    assert "unsupported_extrusion" in codes(read_dxf(path, 3000))
    wide = Settings(extrusion_tolerance=1e-3)
    assert "unsupported_extrusion" not in codes(read_dxf(path, 3000, settings=wide))
    # unrelated to tolerance_mm: widening that does not accept the tilt
    assert "unsupported_extrusion" in codes(
        read_dxf(path, 3000, settings=Settings(tolerance_mm=1.0))
    )
