"""Layer conventions: preset resolution, custom mapping applied, non-standard fixture, access."""

from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.engine.adapters.dxf.reader import read_dxf
from api.engine.conventions import PRESETS, layer_roles, resolve
from api.engine.settings import DEFAULTS
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
H = {"wall_height": 3000, "ceiling_height": 3000}
MAP = {"WALLS": "wall", "ROOMS": "floor", "DOORS": "door", "WINDOWS": "window"}


# ---- engine ---------------------------------------------------------------------------


def test_default_preset_is_current_behaviour():
    assert resolve("aia") == DEFAULTS
    assert resolve("custom") == DEFAULTS and set(PRESETS) == {"aia", "iso13567", "custom"}


def test_iso_preset_names():
    s = resolve("iso13567")
    assert s.wall_layers == {"A-G25---E-", "A-G251--E-", "A-G252--E-"}
    assert (s.floor_layer, s.door_layer, s.window_layer) == ("A-G22---E-", "A-G322--E-", "A-G321--E-")
    assert dict(s.wall_role_layers) == {"A-G251--E-": "exterior", "A-G252--E-": "interior"}
    assert "A-WALL" not in s.wall_layers  # AIA names are unknown under ISO


def test_custom_mapping_resolution():
    s = resolve("custom", {"mywall": "wall", "Ext": "wall_exterior", "d": "door", "w": "window",
                           "f": "floor", "junk": "ignore"})
    assert {"MYWALL", "EXT"} <= s.wall_layers and ("EXT", "exterior") in s.wall_role_layers
    assert s.door_layers == {"A-DOOR", "D"} and s.window_layers == {"A-GLAZ", "W"}
    assert s.floor_layers == {"A-FLOR", "F"} and s.ignore_layers == ("JUNK",)


@pytest.mark.parametrize("preset,mapping,msg", [
    ("nope", {}, "unknown conventions preset"),
    ("aia", {"X": "chimney"}, "unknown role"),
    ("aia", {"a-wall": "door"}, "already mapped"),
    ("aia", {"X": "wall", "x": "door"}, "mapped to both"),
    ("aia", {"L1|A-WALL": "door"}, "already mapped"),
    ("aia", {" ": "wall"}, "must not be empty"),
])
def test_bad_conventions(preset, mapping, msg):
    with pytest.raises(ValueError, match=msg):
        resolve(preset, mapping)


def _summary(p):
    b = p.buildings[0]
    return {k: len(getattr(b, k)) for k in ("walls", "openings") if hasattr(b, k)} | {
        "floors": len(b.floors)}


def test_nonstandard_fixture_needs_mapping():
    path = INPUT / "fixture_nonstandard.dxf"
    bare = read_dxf(path, **H)
    codes = {i.code for i in bare.issues}
    assert "unmapped_layer" in codes and any(i.severity == "blocking" for i in bare.issues)
    mapped = read_dxf(path, **H, settings=resolve("custom", MAP))
    assert not [i for i in mapped.issues if i.severity == "blocking"]
    assert "unmapped_layer" not in {i.code for i in mapped.issues}
    ref = read_dxf(INPUT / "fixture_openings.dxf", **H)
    assert _summary(mapped) == _summary(ref)
    # identical to the standard-named original once the layer names are renamed back
    back = {"WALLS": "A-WALL", "ROOMS": "A-FLOR", "DOORS": "A-DOOR", "WINDOWS": "A-GLAZ"}
    text = mapped.buildings[0].model_dump_json()
    for new, old in back.items():
        text = text.replace(new, old)
    assert text == ref.buildings[0].model_dump_json()


def test_prefixed_layers_map_by_stripped_name(tmp_path):
    # consolidated-drawing style names: one floor prefix per floor, same layer on each
    doc = ezdxf.readfile(INPUT / "fixture_nonstandard.dxf")
    for e in doc.modelspace():
        e.dxf.layer = f"L1|{e.dxf.layer}"
    out = tmp_path / "prefixed.dxf"
    doc.saveas(out)
    prefixed_map = {f"L1|{k}": v for k, v in MAP.items()}
    s = resolve("custom", prefixed_map)
    assert s.wall_extra == ("WALLS",) and s.door_extra == ("DOORS",)
    assert resolve("custom", {**prefixed_map, "L2|WALLS": "wall"}).wall_extra == ("WALLS",)  # repeat ok
    p = read_dxf(out, **H, settings=s, scope=None)
    assert not [i for i in p.issues if i.severity == "blocking"], p.issues
    assert "unmapped_layer" not in {i.code for i in p.issues}
    roles = {r["layer"]: r["role"] for r in layer_roles("custom", prefixed_map, ["L1|WALLS", "L1|DOORS"])}
    assert roles == {"L1|WALLS": "wall", "L1|DOORS": "door"}


def test_mapping_key_length_capped():
    from api.generations import ConventionsSpec

    with pytest.raises(ValueError, match="at most 255"):
        ConventionsSpec(preset="custom", mapping={"X" * 256: "wall"})


def test_partial_mapping_keeps_reporting_the_rest():
    s = resolve("custom", {"WALLS": "wall", "ROOMS": "floor"})  # DOORS/WINDOWS left unmapped
    p = read_dxf(INPUT / "fixture_nonstandard.dxf", **H, settings=s)
    left = {i.message.split()[1] for i in p.issues if i.code == "unmapped_layer"}
    assert left == {"DOORS", "WINDOWS"}


def test_ignore_is_reported_not_silent():
    s = resolve("custom", {**MAP, "DOORS": "ignore"})
    p = read_dxf(INPUT / "fixture_nonstandard.dxf", **H, settings=s)
    ign = [i for i in p.issues if i.code == "layer_ignored_by_user"]
    assert len(ign) == 1 and "DOORS" in ign[0].message and ign[0].severity == "warning"


def test_iso_preset_generates(tmp_path):
    doc = ezdxf.readfile(INPUT / "fixture_openings.dxf")
    iso = {"A-WALL": "A-G25---E-", "A-FLOR": "A-G22---E-", "A-DOOR": "A-G322--E-", "A-GLAZ": "A-G321--E-"}
    for e in doc.modelspace():
        e.dxf.layer = iso[e.dxf.layer]
    out = tmp_path / "iso.dxf"
    doc.saveas(out)
    p = read_dxf(out, **H, settings=resolve("iso13567"))
    assert not [i for i in p.issues if i.severity == "blocking"]
    assert _summary(p) == _summary(read_dxf(INPUT / "fixture_openings.dxf", **H))


# ---- API ------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def manual_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "submit", lambda job_id: None)


def _upload(c, name="fixture_nonstandard.dxf"):
    return c.post("/api/v1/uploads", content=(INPUT / name).read_bytes()).json()["upload_id"]


def _run(c, path, body):
    jid = c.post(f"/api/v1/jobs{path}", json=body).json()["job_id"]
    jobs.execute(jid)
    return c.get(f"/api/v1/jobs/{jid}").json()


def test_layers_endpoint_and_generation_through_jobs():
    c = TestClient(app)
    up = _upload(c)
    layers = c.post(f"/api/v1/uploads/{up}/layers", json={}).json()["layers"]
    assert {"WALLS", "ROOMS", "DOORS", "WINDOWS"} <= {l["layer"] for l in layers}
    assert all(l["role"] is None for l in layers)
    layers = c.post(f"/api/v1/uploads/{up}/layers", json={"preset": "custom", "mapping": MAP}).json()["layers"]
    assert {l["layer"]: l["role"] for l in layers}["DOORS"] == "door"
    r = c.post(f"/api/v1/uploads/{up}/layers", json={"mapping": {"A-WALL": "door"}})
    assert r.status_code == 422
    bare = c.post(f"/api/v1/uploads/{up}/layers", json={}).json()
    assert any(i["severity"] == "blocking" for i in bare["issues"])
    fixed = c.post(f"/api/v1/uploads/{up}/layers", json={"preset": "custom", "mapping": MAP}).json()
    assert not any(i["severity"] == "blocking" for i in fixed["issues"])

    s = _run(c, "/generations", {"upload_id": up, **H})
    assert s["status"] == "failed" and s["result"]["issues"]
    s = _run(c, "/generations", {"upload_id": up, **H, "conventions": {"preset": "custom", "mapping": MAP}})
    assert s["status"] == "succeeded", s


def test_project_conventions_apply_to_floors_and_access():
    owner, editor, viewer = TestClient(app), TestClient(app), TestClient(app)
    pid = owner.post("/api/v1/projects", json={"name": "H"}).json()["project_id"]
    for c, role in ((editor, "editor"), (viewer, "viewer")):
        email = c.get("/api/v1/auth/me").json()["email"]
        owner.put(f"/api/v1/projects/{pid}/access", json={"email": email, "role": role})
    url = f"/api/v1/projects/{pid}/conventions"
    assert owner.get(url).json() == {"preset": "aia", "mapping": {}}
    spec = {"preset": "custom", "mapping": MAP}
    assert owner.put(url, json={"preset": "custom", "mapping": {"A-WALL": "door"}}).status_code == 422
    assert editor.put(url, json=spec).status_code == 200
    assert viewer.put(url, json=spec).status_code == 404
    assert viewer.get(url).json() == spec

    body = {"upload_id": _upload(editor), "floor_name": "Ground", "elevation": 0, **H}
    s = _run(editor, f"/projects/{pid}/floors", body)  # no conventions in the request: saved ones apply
    assert s["status"] == "succeeded", s
    assert len(owner.get(f"/api/v1/projects/{pid}").json()["floors"]) == 1


def test_presets_listing():
    c = TestClient(app)
    d = c.get("/api/v1/conventions").json()
    assert "ignore" in d["roles"] and [p["id"] for p in d["presets"]] == ["aia", "iso13567", "custom"]
    assert d["presets"][1]["layers"]["A-G322--E-"] == "door"


def test_layers_endpoint_reads_the_drawing_in_the_units_the_user_chose(tmp_path):
    import ezdxf

    doc = ezdxf.new("R2018", setup=False)
    doc.header["$INSUNITS"] = 1  # inches, but drawn in metres: 8 "inches" is a 203 mm building
    for y in (0, 0.15, 4, 4.15):
        doc.modelspace().add_line((0, y), (8, y), dxfattribs={"layer": "A-WALL"})
    path = tmp_path / "m.dxf"
    doc.saveas(path)
    c = TestClient(app)
    up = c.post("/api/v1/uploads", content=path.read_bytes()).json()
    assert "units_implausible" in {i["code"] for i in up["issues"]}  # warned, nothing changed
    r = c.post(f"/api/v1/uploads/{up['upload_id']}/layers?units=m&units_override=true", json={}).json()
    codes = {i["code"] for i in r["issues"]}
    assert "units_overridden" in codes and "units_implausible" not in codes
    assert c.post(f"/api/v1/uploads/{up['upload_id']}/layers?units=km", json={}).status_code == 422
