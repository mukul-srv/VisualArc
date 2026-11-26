"""Edit ops on walls and openings off the axes (26c): add/move/resize/remove a diagonal wall, openings on it."""

import importlib.util
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.engine.adapters.dxf.reader import read_dxf
from api.engine.edits import EditsRequest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("make_fixture_diagonal", ROOT / "scripts/make_fixture_diagonal.py")
_mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mk)
S2 = math.sqrt(2)


def _run(tmp_path, ops=(), window=True):
    path = _mk.build(tmp_path / "e.dxf", window=window)
    edits = EditsRequest.model_validate({"edits": list(ops)}).edits
    p = read_dxf(path, 2700, ceiling_height=2700, edits=edits)
    return p, p.buildings[0].floors[0]


def _diag(f):
    return next(w for w in f.walls if w.centreline.start[0] != w.centreline.end[0] and w.centreline.start[1] != w.centreline.end[1])


def _ref(w):
    return {"start": w.centreline.start, "end": w.centreline.end, "thickness": w.thickness.value,
            "handles": [s.entity_handle for s in w.sources]}


def _oref(o):
    return {"kind": o.kind, "start": o.span.start, "end": o.span.end, "handles": [s.entity_handle for s in o.sources]}


def _codes(p):
    return [i.code for i in p.issues]


def test_slanted_ops_validate_and_must_follow_their_wall():
    wall = {"start": [0, 0], "end": [1000, 1000], "thickness": 200, "handles": ["1"]}
    add = {"op": "add_opening", "id": "o1", "wall": wall, "kind": "door", "start": [200, 200], "end": [700, 700]}
    EditsRequest.model_validate({"edits": [add]})
    with pytest.raises(ValidationError, match="along its wall"):
        EditsRequest.model_validate({"edits": [{**add, "end": [700, 200]}]})


def test_added_diagonal_wall_is_built_with_user_modified_thickness(tmp_path):
    _, f = _run(tmp_path, [{"op": "add_wall", "id": "e1", "start": [500, 500], "end": [2500, 2500], "thickness": 160}], window=False)
    w = next(w for w in f.walls if any(s.entity_handle == "e1" for s in w.sources))
    (x0, y0), (x1, y1) = w.centreline.start, w.centreline.end
    assert math.degrees(math.atan2(y1 - y0, x1 - x0)) == pytest.approx(45.0, abs=1e-6)
    assert math.dist((x0, y0), (x1, y1)) == pytest.approx(2000 * S2, abs=1e-6)
    assert w.thickness.value == pytest.approx(160, abs=1e-6) and w.thickness.source == "user_modified"
    assert all(s.format == "edit" for s in w.sources)


def test_moving_a_diagonal_wall_takes_its_window_along(tmp_path):
    _, f = _run(tmp_path)
    w, o = _diag(f), f.openings[0]
    (x0, y0), (x1, y1) = w.centreline.start, w.centreline.end
    op = {"op": "set_wall", "id": "m1", "target": _ref(w), "start": [x0 - 300, y0], "end": [x1 - 300, y1], "thickness": 200}
    _, g = _run(tmp_path, [op])
    (o2,) = g.openings
    assert o2.wall_id == _diag(g).id and o2.width.value == pytest.approx(o.width.value, abs=1e-6)
    assert o2.span.start[0] == pytest.approx(o.span.start[0] - 300, abs=1e-6)  # shifted with the wall, same offset
    assert o2.offset.value == pytest.approx(o.offset.value, abs=1e-6)


def test_resizing_a_diagonal_wall_keeps_the_window_where_it_is_or_reports_it(tmp_path):
    _, f = _run(tmp_path)
    w, o = _diag(f), f.openings[0]
    (x0, y0), (x1, y1) = w.centreline.start, w.centreline.end
    longer = {"op": "set_wall", "id": "m1", "target": _ref(w), "start": [x0, y0], "end": [x1 - 100, y1 + 100], "thickness": 200}
    p, g = _run(tmp_path, [longer])
    (o2,) = g.openings
    assert o2.span.start == pytest.approx(o.span.start, abs=1e-6) and "edit_opening_removed" not in _codes(p)
    shorter = {**longer, "end": [x0 - 400, y0 + 400]}  # the wall now ends before the window
    p, g = _run(tmp_path, [shorter])
    assert not g.openings and "edit_opening_removed" in _codes(p)


def test_removing_a_diagonal_wall_reports_its_window(tmp_path):
    _, f = _run(tmp_path)
    p, g = _run(tmp_path, [{"op": "remove_wall", "id": "r1", "target": _ref(_diag(f))}])
    assert len(g.walls) == 4 and not g.openings and "edit_opening_removed" in _codes(p)


def test_opening_added_resized_and_removed_on_a_diagonal_wall(tmp_path):
    _, f = _run(tmp_path, window=False)
    w = _diag(f)
    (x0, y0), (x1, y1) = w.centreline.start, w.centreline.end
    u = ((x1 - x0) / math.dist((x0, y0), (x1, y1)), (y1 - y0) / math.dist((x0, y0), (x1, y1)))
    at = lambda s: [x0 + s * u[0], y0 + s * u[1]]
    add = {"op": "add_opening", "id": "a1", "wall": _ref(w), "kind": "door", "start": at(600), "end": at(1500), "height": 2000, "sill_height": 0}
    _, g = _run(tmp_path, [add], window=False)
    (o,) = g.openings
    assert o.kind == "door" and o.wall_id == _diag(g).id and o.width.value == pytest.approx(900, abs=1e-6)
    assert o.offset.value == pytest.approx(600, abs=1e-6) and o.height.source == "user_modified"
    assert o.offset.source == "user_modified" and o.sources[0].format == "edit"
    resize = {"op": "set_opening", "id": "a2", "target": _oref(o), "kind": "door", "start": at(600), "end": at(1700)}
    _, g2 = _run(tmp_path, [add, resize], window=False)
    (o2,) = g2.openings
    assert o2.width.value == pytest.approx(1100, abs=1e-6) and o2.width.source == "user_modified"
    gone = {"op": "remove_opening", "id": "a3", "target": _oref(o)}
    p3, g3 = _run(tmp_path, [add, gone], window=False)
    assert not g3.openings and len(g3.walls) == 5  # the wall is solid again, one wall
    assert "unmarked_wall_gap" not in _codes(p3) and "edit_target_missing" not in _codes(p3)


def test_stale_diagonal_target_is_reported_not_applied(tmp_path):
    _, f = _run(tmp_path)
    ref = _ref(_diag(f))
    ref["start"] = [ref["start"][0] + 500, ref["start"][1]]  # a wall that is not in the drawing any more
    p, g = _run(tmp_path, [{"op": "remove_wall", "id": "r1", "target": ref}])
    assert "edit_target_missing" in _codes(p) and len(g.walls) == 5
