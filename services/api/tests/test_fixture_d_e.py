"""Fixture D (scalable larger floor) and Fixture E (multi-storey source set), T21.

Timings are NOT asserted here (scripts/benchmark.py measures them); these tests pin
the correctness of the benchmark inputs so a benchmark result can be trusted.
"""

import importlib.util
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api.engine.adapters.dxf.reader import read_dxf
from api.main import app

ROOT = Path(__file__).resolve().parents[3]
INPUT = ROOT / "fixtures" / "input"
_spec = importlib.util.spec_from_file_location(
    "make_fixture_d", ROOT / "scripts" / "make_fixture_d.py"
)
make_d = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_d)
PER_TILE = make_d.PER_TILE


def _counts(project):
    f = project.buildings[0].floors[0]
    return {
        "walls": len(f.walls),
        "junctions": len(f.junctions),
        "floor boundaries": len(f.boundaries),
        "openings": len(f.openings),
    }


def test_per_tile_counts_match_fixture_openings():
    assert _counts(read_dxf(INPUT / "fixture_openings.dxf", 3000)) == PER_TILE


def test_committed_fixture_d_is_nine_tiles_with_exact_counts():
    p = read_dxf(INPUT / "fixture_d.dxf", 3000)
    assert [i.severity for i in p.issues].count("blocking") == 0
    assert _counts(p) == {k: v * 9 for k, v in PER_TILE.items()}
    thick = {w.thickness.value for w in p.buildings[0].floors[0].walls}
    assert thick == {100, 200}


@pytest.mark.parametrize("offset", [0, 1e6, 1e8])
def test_far_from_origin_geometry_is_unchanged(tmp_path, offset):
    """Extent probe: translating the plan must not change walls or openings."""
    make_d.make(1, 1, tmp_path / "t.dxf", offset_mm=offset)
    p = read_dxf(tmp_path / "t.dxf", 3000)
    ref = read_dxf(INPUT / "fixture_openings.dxf", 3000)
    assert _counts(p) == _counts(ref)
    fp, fr = p.buildings[0].floors[0], ref.buildings[0].floors[0]
    assert sorted(w.thickness.value for w in fp.walls) == pytest.approx(
        sorted(w.thickness.value for w in fr.walls), abs=1e-6
    )
    assert sorted(o.width.value for o in fp.openings) == pytest.approx(
        sorted(o.width.value for o in fr.openings), abs=1e-6
    )


# --- Fixture E: one floor per job ------------------------------------------
FLOORS = {  # storey -> existing valid drawing, with expected footprint (mm)
    "ground": ("fixture_a.dxf", (8200, 5200)),
    "first": ("fixture_openings.dxf", (9600, 4000)),
    "roof": ("fixture_b.dxf", (6000, 5000)),
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


def _job(client, name):
    up = client.post("/api/v1/uploads", content=(INPUT / name).read_bytes()).json()
    gen = client.post(
        "/api/v1/generations", json={"upload_id": up["upload_id"], "wall_height": 3000}
    )
    assert gen.status_code == 201
    body = gen.json()
    canon = client.get(body["artifacts"]["canonical"]).json()
    return body["generation_id"], canon["buildings"][0]["floors"][0]


def test_each_storey_is_its_own_job_and_never_combined(client):
    jobs = {k: _job(client, f) for k, (f, _) in FLOORS.items()}
    assert len({gid for gid, _ in jobs.values()}) == 3  # distinct jobs
    for k, (gid, floor) in jobs.items():
        name, _ = FLOORS[k]
        solo = read_dxf(INPUT / name, 3000).buildings[0].floors[0]
        # same element counts as processing that drawing alone: nothing carried over
        assert len(floor["walls"]) == len(solo.walls)
        assert len(floor["openings"]) == len(solo.openings)
        assert floor["walls"][0]["id"] == "wall-001"  # ids restart per job
        assert floor["id"] == "floor-0"


def test_job_result_does_not_depend_on_what_was_processed_before(client):
    first = _job(client, "fixture_a.dxf")[1]
    _job(client, "fixture_openings.dxf")
    again = _job(client, "fixture_a.dxf")[1]
    assert first == again


def test_two_plans_in_one_file_are_one_floor_known_limitation(tmp_path):
    """KNOWN LIMITATION (reported in the T21 benchmark): the engine has no notion of
    several storeys in one DXF. Two plans drawn side by side are interpreted as ONE
    floor, silently. This pins today's behaviour; revisit if a warning is added."""
    doc = ezdxf.new("R2018", setup=False)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for name, dx in (("fixture_a.dxf", 0), ("fixture_b.dxf", 20000)):
        for e in ezdxf.readfile(INPUT / name).modelspace():
            c = e.copy()
            c.translate(dx, 0, 0)
            msp.add_entity(c)
    doc.saveas(tmp_path / "two.dxf")
    p = read_dxf(tmp_path / "two.dxf", 3000)
    assert len(p.buildings) == 1 and len(p.buildings[0].floors) == 1
    solo = [
        read_dxf(INPUT / n, 3000).buildings[0].floors[0]
        for n in ("fixture_a.dxf", "fixture_b.dxf")
    ]
    assert len(p.buildings[0].floors[0].walls) == sum(len(f.walls) for f in solo)
    assert not [i for i in p.issues if i.severity == "blocking"]
