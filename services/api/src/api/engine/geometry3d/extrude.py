"""Canonical floor -> triangle meshes, one per element.

Output stays in plan space: millimetres, X/Y = plan, Z up, Z=0 at datum.
The swap to glTF Y-up (ADR-001) belongs to the exporter, not here.
"""

import math

import numpy as np
import trimesh
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from api.engine.canonical.model import Balcony, Floor, Opening, Roof, Wall, _axis


def _height(w: Wall) -> float:
    if w.height is None:  # reader already raised a blocking issue for this
        raise ValueError(f"{w.id} has no height; cannot extrude")
    return w.height.value


def _prism(footprint: Polygon, z0: float, height: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.extrude_polygon(footprint, height)
    mesh.apply_translation((0, 0, z0))
    return mesh


def _flat(polygon: Polygon, z: float, up: bool = True) -> trimesh.Trimesh:
    # no slab thickness in the canonical model -> zero-thickness surface
    v2, faces = trimesh.creation.triangulate_polygon(orient(polygon, 1.0))
    v3 = np.column_stack([v2, np.full(len(v2), z)])
    return trimesh.Trimesh(v3, faces if up else faces[:, ::-1], process=True)


def _wall_with_openings(
    w: Wall, openings: list[Opening], z0: float, height: float
) -> trimesh.Trimesh:
    """Elevation profile (u along centreline, v up) minus apertures, extruded
    through the full thickness, then placed on the centreline: one closed mesh."""
    start, end = np.array(w.centreline.start), np.array(w.centreline.end)
    length = float(np.linalg.norm(end - start))
    d = (end - start) / length
    holes = []
    for o in openings:  # u from the span itself, so exact even if start > end
        us = sorted(
            float(np.dot(np.array(p) - start, d)) for p in (o.span.start, o.span.end)
        )
        top = o.sill_height.value + o.height.value
        holes.append(box(us[0], o.sill_height.value, us[1], top))
    profile = box(0, 0, length, height).difference(unary_union(holes))
    # a full-height aperture splits the wall into separate closed pieces
    parts = getattr(profile, "geoms", [profile])
    t = w.thickness.value
    mesh = trimesh.util.concatenate(
        [trimesh.creation.extrude_polygon(p, t) for p in parts]
    )
    # local (u, v, w) -> plan; n = (dy, -dx) makes det = +1, so winding survives
    nx, ny = d[1], -d[0]
    sx, sy = start - np.array([nx, ny]) * t / 2
    mesh.apply_transform(
        [[d[0], 0, nx, sx], [d[1], 0, ny, sy], [0, 1, 0, z0], [0, 0, 0, 1]]
    )
    return mesh


def _slab_box(axis: int, a0, a1, n0, n1, z0, z1) -> trimesh.Trimesh:
    """Box from along-wall range [a0, a1], across-wall range [n0, n1] and height range [z0, z1]."""
    lo = (a0, n0, z0) if axis == 0 else (n0, a0, z0)
    hi = (a1, n1, z1) if axis == 0 else (n1, a1, z1)
    return trimesh.creation.box(bounds=[lo, hi])


def build_opening_parts(floor: Floor) -> dict[str, tuple[str, Opening, trimesh.Trimesh]]:
    """Medium detail per opening with a `detail`: `<id>-frame` and `<id>-leaf` / `<id>-glass`
    (id -> (part, opening, mesh)). The panel is drawn closed, centred in the wall."""
    walls = {w.id: w for w in floor.walls}
    out = {}
    for o in floor.openings:
        d = o.detail
        if d is None:
            continue
        axis = _axis(o.span)
        a0, a1 = sorted((o.span.start[axis], o.span.end[axis]))
        c = o.span.start[1 - axis]
        t, fw, pt = walls[o.wall_id].thickness.value, d.frame_width.value, d.panel_thickness.value
        s = floor.elevation.value + o.sill_height.value
        top = s + o.height.value
        door = d.panel == "leaf"

        def box(x0, x1, z0, z1, depth=t, axis=axis, c=c):
            return _slab_box(axis, x0, x1, c - depth / 2, c + depth / 2, z0, z1)

        frame = [box(a0, a0 + fw, s, top), box(a1 - fw, a1, s, top),
                 box(a0 + fw, a1 - fw, top - fw, top)]
        if not door:
            frame.append(box(a0 + fw, a1 - fw, s, s + fw))
        out[f"{o.id}-frame"] = ("frame", o, trimesh.util.concatenate(frame))
        out[f"{o.id}-{d.panel}"] = (
            d.panel, o, box(a0 + fw, a1 - fw, s if door else s + fw, top - fw, pt))
    return out


def build_balcony_railings(floor: Floor) -> dict[str, tuple[Balcony, trimesh.Trimesh]]:
    """`<balcony id>-railing`: one box per free edge, `railing_height` tall from the floor
    elevation, `railing_thickness` wide centred on the edge (flat caps, like walls)."""
    out = {}
    for b in floor.balconies:
        if not b.railings or b.railing_height is None or b.railing_thickness is None:
            continue
        parts = [
            _prism(
                LineString([r.start, r.end]).buffer(b.railing_thickness.value / 2, cap_style="flat"),
                floor.elevation.value, b.railing_height.value,
            )
            for r in b.railings
        ]
        out[f"{b.id}-railing"] = (b, trimesh.util.concatenate(parts))
    return out


def _flight_frame(polygon, direction):
    """(axis, bottom coordinate, sign, n0, n1, length): the flight along its direction."""
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    axis, sign = (0 if direction[1] == "x" else 1), (1 if direction[0] == "+" else -1)
    lo, hi = (min(xs), max(xs)) if axis == 0 else (min(ys), max(ys))
    n0, n1 = (min(ys), max(ys)) if axis == 0 else (min(xs), max(xs))
    return axis, (lo if sign > 0 else hi), sign, n0, n1, hi - lo


def build_stair(s, z0: float) -> trimesh.Trimesh | None:
    """Solid steps: block k (1..n-1) spans its tread and rises k risers above the floor."""
    if s.riser_count is None:
        return None
    axis, bottom, sign, n0, n1, _ = _flight_frame(s.polygon, s.direction)
    g, r = s.tread_depth.value, s.riser_height.value
    blocks = []
    for k in range(1, s.riser_count):
        a, b = sorted((bottom + sign * (k - 1) * g, bottom + sign * k * g))
        blocks.append(_slab_box(axis, a, b, n0, n1, z0, z0 + k * r))
    return trimesh.util.concatenate(blocks)


def build_ramp(r, z0: float) -> trimesh.Trimesh | None:
    """Inclined slab: top from the floor (bottom end) up by `rise`, `thickness` thick vertically."""
    if r.rise is None or r.thickness is None or r.direction is None:
        return None
    axis, bottom, sign, n0, n1, length = _flight_frame(r.polygon, r.direction)
    t = r.thickness.value
    a0, a1 = sorted((bottom, bottom + sign * length))
    mesh = _slab_box(axis, a0, a1, n0, n1, z0 - t, z0)  # flat slab, then shear z by the slope
    k = sign * r.rise.value / length  # dz per mm along the plan axis; det = 1, winding survives
    row = [0.0, 0.0, 1.0, -k * bottom]
    row[axis] = k
    mesh.apply_transform([[1, 0, 0, 0], [0, 1, 0, 0], row, [0, 0, 0, 1]])
    return mesh


def _convex_solid(vertices: list, tris: list[tuple[int, int, int]]) -> trimesh.Trimesh:
    """Triangles of a convex solid, each wound to face away from the centroid (no hull needed)."""
    v = np.array(vertices, dtype=float)
    c = v.mean(axis=0)
    faces = []
    for a, b, d in tris:
        if len({a, b, d}) < 3:  # collapsed (a hip ridge of length 0)
            continue
        n = np.cross(v[b] - v[a], v[d] - v[a])
        faces.append((a, b, d) if np.dot(n, (v[a] + v[b] + v[d]) / 3 - c) > 0 else (a, d, b))
    return trimesh.Trimesh(v, faces, process=True)


def build_roof(r: Roof) -> trimesh.Trimesh | None:
    """Flat: a slab on the wall tops. Gable/hip: the solid volume between the eaves plane (wall
    tops) and the roof surface, which overhangs the outline on every side."""
    if r.base_elevation is None:
        return None
    z = r.base_elevation.value
    if r.kind == "flat":
        return _prism(Polygon(r.polygon), z, r.thickness.value)
    xs, ys = [p[0] for p in r.polygon], [p[1] for p in r.polygon]
    o = r.overhang.value
    x0, x1, y0, y1 = min(xs) - o, max(xs) + o, min(ys) - o, max(ys) + o
    h, along_x = r.ridge_height.value, r.ridge_axis == "x"
    inset = 0.0 if r.kind == "gable" else min(x1 - x0, y1 - y0) / 2  # hip: ridge ends pulled in
    if along_x:
        top = [(x0 + inset, (y0 + y1) / 2), (x1 - inset, (y0 + y1) / 2)]
    else:
        top = [((x0 + x1) / 2, y0 + inset), ((x0 + x1) / 2, y1 - inset)]
    v = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), *[(a, b, z + h) for a, b in top]]
    top1 = 5
    if math.dist(top[0], top[1]) < 1e-6:  # a hip over a square: one apex
        v.pop()
        top1 = 4
    quads = [(0, 1, 2, 3)]  # the eaves plane
    if along_x:  # south slope, north slope, west end, east end (a triangle when the ridge is inset 0)
        quads += [(0, 1, top1, 4), (2, 3, 4, top1), (0, 3, 4, 4), (1, 2, top1, top1)]
    else:
        quads += [(0, 3, top1, 4), (1, 2, top1, 4), (0, 1, 4, 4), (2, 3, top1, top1)]
    tris = [t for q in quads for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]
    return _convex_solid(v, tris)


def build_meshes(floor: Floor) -> dict[str, trimesh.Trimesh]:
    """Element id -> mesh for every wall, junction, floor boundary, slab and ceiling."""
    z0 = floor.elevation.value
    heights = {w.id: _height(w) for w in floor.walls}
    hosted: dict[str, list[Opening]] = {}
    for o in floor.openings:
        hosted.setdefault(o.wall_id, []).append(o)
    meshes = {}
    for w in floor.walls:
        if w.id in hosted:
            meshes[w.id] = _wall_with_openings(w, hosted[w.id], z0, heights[w.id])
            continue
        # unchanged path: walls without openings stay byte-identical to pre-T12
        line = LineString([w.centreline.start, w.centreline.end])
        rect = line.buffer(w.thickness.value / 2, cap_style="flat")
        meshes[w.id] = _prism(rect, z0, heights[w.id])
    for j in floor.junctions:
        # corner fill must reach the tallest wall it joins, else a notch shows
        meshes[j.id] = _prism(
            Polygon(j.polygon), z0, max(heights[i] for i in j.wall_ids)
        )
    for b in floor.boundaries:
        meshes[b.id] = _flat(Polygon(b.polygon), z0)
    for st in floor.stairs:  # without direction or heights: reported by the reader, no mesh
        if (m := build_stair(st, z0)) is not None:
            meshes[st.id] = m
    for rp in floor.ramps:
        if (m := build_ramp(rp, z0)) is not None:
            meshes[rp.id] = m
    for rf in floor.roofs:  # no base elevation (no wall height): recorded, not built
        if (m := build_roof(rf)) is not None:
            meshes[rf.id] = m
    for col in floor.columns:
        if col.height is None:  # ceiling height missing: blocking, nothing is exported
            continue
        foot = (Polygon(col.polygon) if col.shape == "rect"
                else Point(col.centre).buffer(col.radius.value, quad_segs=16))
        meshes[col.id] = _prism(foot, z0, col.height.value)
    for bal in floor.balconies:
        t = bal.thickness.value if bal.thickness else 0.0
        meshes[bal.id] = (_prism(Polygon(bal.polygon), z0 - t, t) if t
                          else _flat(Polygon(bal.polygon), z0))
    for sl in floor.slabs:
        t = sl.thickness.value
        m = _prism(Polygon(sl.polygon), z0 - t, t)
        # the top face is the floor boundary's surface: drop it here (open top) so the two
        # coplanar faces do not z-fight; boundary + slab together are the closed solid
        top = (m.face_normals[:, 2] > 0.5) & (m.triangles_center[:, 2] > z0 - 1e-6)
        m.update_faces(~top)
        m.remove_unreferenced_vertices()
        meshes[sl.id] = m
    for c in floor.ceilings:  # underside faces down so it shows from inside
        meshes[c.id] = _flat(Polygon(c.polygon), c.elevation.value, up=False)
    return meshes
