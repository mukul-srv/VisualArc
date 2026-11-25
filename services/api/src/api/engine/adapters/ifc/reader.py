"""IFC -> canonical Project (IfcOpenShell, used as a library only; it is LGPL).

One floor per IfcBuildingStorey. Geometry is read from the tessellated shape in world coordinates
(IfcOpenShell returns metres whatever the file's unit, so the unit of the IfcProject is honoured; storey
elevations are converted with the project's length unit). Every element keeps a SourceRef with
format "ifc", layer = IFC class and entity_handle = GlobalId. Values read from the geometry are
`source_extracted`, values derived from them `inferred`, nominal values `defaulted`.

Provenance note: Room has no `sources`, so a space's GlobalId rides in `label_sources`.

Supported: IfcWall (a rectangle: centreline + thickness), IfcSlab, IfcDoor / IfcWindow (hosted through
IfcOpeningElement), IfcSpace, IfcStair (straight block stairs), IfcColumn, IfcRoof. Anything else, and
anything that cannot be read, is an issue: nothing is dropped silently.
"""

import math
from collections import defaultdict
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel
import ifcopenshell.util.unit as uunit
import numpy as np
from pydantic import ValidationError
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

from api.engine.adapters.dxf.reader import InputError
from api.engine.canonical.model import (
    Area,
    Building,
    Column,
    Floor,
    Issue,
    LineGeometry,
    Measured,
    Opening,
    OpeningDetail,
    Param,
    Project,
    Roof,
    Room,
    Slab,
    SourceRef,
    Stair,
    Wall,
    _axis,
)
from api.engine.settings import DEFAULTS, Settings

HANDLED = ("IfcWall", "IfcSpace", "IfcSlab", "IfcDoor", "IfcWindow", "IfcColumn", "IfcStair", "IfcRoof", "IfcOpeningElement")
_MM = 1000.0  # IfcOpenShell geometry is metres


def is_ifc(path: Path) -> bool:
    """STEP header sniff (`ISO-10303-21;`), so an upload's kind never depends on its file name."""
    with path.open("rb") as f:
        return f.read(64).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"ISO-10303-21")


def _ref(el) -> SourceRef:
    return SourceRef(format="ifc", layer=el.is_a(), entity_handle=el.GlobalId)


def _m(value: float, source="source_extracted") -> Measured:
    return Measured(value=float(value), source=source)


class _Ctx:
    def __init__(self, model, settings: Settings):
        self.model, self.s = model, settings
        self.geo = ifcopenshell.geom.settings()
        self.geo.set("use-world-coords", True)
        self.issues: list[Issue] = []
        self.cache: dict[int, tuple[np.ndarray, np.ndarray] | None] = {}

    def issue(self, code, message, els=(), severity="warning"):
        self.issues.append(Issue(code=code, severity=severity, message=message,
                                 sources=[_ref(e) for e in els][: self.s.unmapped_ref_cap]))

    def mesh(self, el):
        """(vertices in mm (N,3), faces (M,3)) in world coordinates, or None (an issue is recorded)."""
        if el.id() in self.cache:
            return self.cache[el.id()]
        out = None
        if el.Representation is None:
            self.issue("ifc_no_geometry", f"{el.is_a()} {el.GlobalId} has no geometry; not imported", [el])
        else:
            try:
                g = ifcopenshell.geom.create_shape(self.geo, el).geometry
                v = np.array(g.verts, dtype=float).reshape(-1, 3) * _MM
                f = np.array(g.faces, dtype=int).reshape(-1, 3)
                if len(v) and len(f):
                    out = (v, f)
            except Exception as e:  # noqa: BLE001  IfcOpenShell raises RuntimeError for unsupported shapes
                self.issue("ifc_geometry_unreadable",
                           f"{el.is_a()} {el.GlobalId}: geometry could not be read ({e}); not imported", [el])
        self.cache[el.id()] = out
        return out

    def footprint(self, el):
        """(Polygon in mm, zmin, zmax) of the shape seen from above, or None."""
        mv = self.mesh(el)
        if mv is None:
            return None
        v, f = mv
        tris = [Polygon(v[t][:, :2]) for t in f]
        poly = unary_union([t for t in tris if t.area > 1e-9]).buffer(
            self.s.ifc_snap_mm / 10, join_style="mitre").buffer(-self.s.ifc_snap_mm / 10, join_style="mitre")
        if poly.is_empty:
            self.issue("ifc_geometry_unreadable", f"{el.is_a()} {el.GlobalId} has no footprint; not imported", [el])
            return None
        if poly.geom_type == "MultiPolygon":
            self.issue("ifc_footprint_parts", f"{el.is_a()} {el.GlobalId} has several separate parts; the "
                       "largest is imported", [el])
            poly = max(poly.geoms, key=lambda p: p.area)
        return poly.simplify(self.s.ifc_snap_mm / 10), float(v[:, 2].min()), float(v[:, 2].max())


def _snap(a: float, b: float, tol: float) -> tuple[float, float]:
    return (a, a) if abs(a - b) <= tol else (a, b)


def _rect_axes(poly: Polygon, tol: float):
    """(corners, long edge index) of the minimum rotated rectangle, axis-aligned corners snapped."""
    c = list(MultiPoint(list(poly.exterior.coords)).minimum_rotated_rectangle.exterior.coords)[:4]
    xs, ys = [p[0] for p in c], [p[1] for p in c]
    for coords in (xs, ys):  # an axis-aligned rectangle must come out exactly aligned
        for i in range(4):
            for j in range(i):
                if abs(coords[i] - coords[j]) <= tol:
                    coords[i] = coords[j]
    return list(zip(xs, ys, strict=True))


def _wall(ctx: _Ctx, el, n: int):
    fp = ctx.footprint(el)
    if fp is None:
        return None
    poly, z0, z1 = fp
    c = _rect_axes(poly, ctx.s.ifc_snap_mm)
    e0, e1 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
    if poly.area < ctx.s.ifc_rect_fill * e0 * e1:
        ctx.issue("ifc_wall_approximated", f"IfcWall {el.GlobalId} is not a rectangle in plan; imported as its "
                  "bounding rectangle", [el])
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if e0 >= e1:
        s, e, t = mid(c[0], c[3]), mid(c[1], c[2]), e1
    else:
        s, e, t = mid(c[0], c[1]), mid(c[3], c[2]), e0
    if (e[0], e[1]) < (s[0], s[1]):
        s, e = e, s
    return s, e, t, z0, z1


def storeys(path: Path) -> list[dict]:
    """The file's storeys, lowest first: key (GlobalId), name, elevation in mm (None when the file has none)."""
    model = ifcopenshell.open(str(path))
    unit_mm = uunit.calculate_unit_scale(model) * _MM
    return [{"key": s.GlobalId, "name": s.Name or s.GlobalId,
             "elevation": None if s.Elevation is None else float(s.Elevation) * unit_mm}
            for s in sorted(model.by_type("IfcBuildingStorey"), key=lambda s: (s.Elevation or 0.0, s.GlobalId))]


def read_ifc(path: Path, storey: str | None = None, floor_id: str | None = None, floor_name: str | None = None,
             floor_elevation: float | None = None, elevation_assumed: str | None = None,
             settings: Settings = DEFAULTS) -> Project:
    """The file as a Project (one floor per storey); `storey` = a storey GlobalId reads only that floor,
    named/identified/elevated by the caller's values when given (an elevation the caller assumed is
    `defaulted`, one equal to the storey's own stays `source_extracted`)."""
    project = {"id": path.stem, "source_file": path.name}
    try:
        model = ifcopenshell.open(str(path))
    except Exception as e:
        raise InputError(f"not a readable IFC file: {e}") from e
    if model.schema not in ("IFC2X3", "IFC4", "IFC4X3_ADD2", "IFC4X3"):
        raise InputError(f"IFC schema {model.schema} is not supported")
    if not model.by_type("IfcProject") or not model.by_type("IfcUnitAssignment"):
        return Project(**project, issues=[Issue(
            code="ifc_units_missing", severity="blocking",
            message="the IFC file has no length unit (IfcProject.UnitsInContext); refusing to guess")])
    ctx = _Ctx(model, settings)
    storeys = sorted(model.by_type("IfcBuildingStorey"), key=lambda s: (s.Elevation or 0.0, s.GlobalId))
    if not storeys:
        return Project(**project, issues=[Issue(
            code="ifc_no_storeys", severity="blocking", message="the IFC file has no IfcBuildingStorey")])
    if storey is not None:
        match = [s for s in storeys if s.GlobalId == storey]
        if not match:
            raise InputError(f"unknown storey {storey}")
        storeys = match
    unit_mm = uunit.calculate_unit_scale(model) * _MM  # project length unit -> mm (storey Elevation)
    floors, seen = [], set()
    for i, st in enumerate(storeys):
        seen.add(st.id())
        floors.append(_floor(ctx, st, floor_id or f"floor-{i}", floor_name or st.Name or f"Storey {i}",
                             floor_elevation, unit_mm, elevation_assumed))
    if storey is None:  # elements outside every storey, once for the whole file
        placed = {e.id() for st in model.by_type("IfcBuildingStorey") for e in uel.get_decomposition(st)}
        _unsupported(ctx, [e for e in model.by_type("IfcElement") if e.id() not in placed], "not in any storey")
    return Project(**project, buildings=[Building(id="bldg-0", floors=floors)], issues=ctx.issues,
                   parameters={"ifc_schema": Param(value=model.schema, unit="none", source="source_extracted")})


def _unsupported(ctx: _Ctx, els, where: str):
    by = defaultdict(list)
    for e in els:
        if not e.is_a("IfcOpeningElement") and not any(e.is_a(h) for h in HANDLED):
            by[e.is_a()].append(e)
    for cls, items in sorted(by.items()):
        ctx.issue("ifc_unsupported_entity", f"{len(items)} {cls} ({where}) not imported: unsupported type", items)


def _floor(ctx: _Ctx, st, fid: str, name: str, forced_elev: float | None, unit_mm: float,
           assumed: str | None = None) -> Floor:
    s = ctx.s
    els = uel.get_decomposition(st)
    _unsupported(ctx, els, f"storey {st.Name or st.GlobalId}")
    of = lambda cls: [e for e in els if e.is_a(cls)]
    # slabs first: the finished level (elevation + slab thickness) is the reference of every height
    slabs, roofs = [], []
    for e in of("IfcSlab"):
        (roofs if e.PredefinedType == "ROOF" else slabs).append(e)
    roofs += of("IfcRoof")
    slab_fp = [(e, ctx.footprint(e)) for e in slabs]
    slab_fp = [(e, f) for e, f in slab_fp if f is not None]
    walls = [(e, _wall(ctx, e, 0)) for e in of("IfcWall")]
    walls = [(e, w) for e, w in walls if w is not None]
    if forced_elev is not None:
        own = None if st.Elevation is None else float(st.Elevation) * unit_mm
        elev = forced_elev
        src = ("defaulted" if assumed else "source_extracted" if own is not None and abs(own - elev) <= s.ifc_snap_mm
               else "user_provided")
    elif st.Elevation is not None:
        elev, src = float(st.Elevation) * unit_mm, "source_extracted"
    else:
        zs = [w[3] for _, w in walls] + [f[1] for _, f in slab_fp]
        elev, src = (min(zs) if zs else 0.0), "inferred"
        ctx.issue("ifc_elevation_inferred", f"storey {st.Name or st.GlobalId} has no Elevation; the lowest "
                  f"element level {elev:g} mm is used", [st])
    for e, (_, z0, _) in slab_fp:
        if abs(z0 - elev) > s.ifc_snap_mm:
            ctx.issue("ifc_slab_off_elevation", f"IfcSlab {e.GlobalId} starts {z0 - elev:g} mm from the storey "
                      "elevation; the elevation is read as the underside of the floor slab", [e])
    slab_models = [Slab(id=f"slab-{n:03d}", polygon=list(p.exterior.coords)[:-1], holes=[],
                        thickness=_m(z1 - z0), sources=[_ref(e)])
                   for n, (e, (p, z0, z1)) in enumerate(slab_fp, 1) if z1 - z0 > 0]
    finished = elev + max((sl.thickness.value for sl in slab_models), default=0.0)

    wall_models, wall_of = [], {}
    for n, (e, (a, b, t, z0, z1)) in enumerate(walls, 1):
        if z1 - finished <= 0 or t <= 0:
            ctx.issue("ifc_wall_degenerate", f"IfcWall {e.GlobalId} has no height above the finished floor or "
                      "no thickness; not imported", [e])
            continue
        w = Wall(id=f"wall-{n:03d}", centreline=LineGeometry(start=a, end=b), thickness=_m(t),
                 height=_m(z1 - finished), sources=[_ref(e)])
        wall_models.append(w)
        wall_of[e.id()] = w
    openings = _openings(ctx, els, wall_of, finished, walls, wall_models)

    rooms, heights = [], []
    for e in of("IfcSpace"):
        fp = ctx.footprint(e)
        if fp is None:
            continue
        p, z0, z1 = fp
        heights.append(z1 - finished)
        label = (e.LongName or e.Name or "").strip()
        n = len(rooms) + 1
        rooms.append(Room(id=f"room-{n:03d}", name=label or f"Room {n}", name_source="source_extracted" if label else "defaulted",
                          polygon=list(p.exterior.coords)[:-1], holes=[list(r.coords)[:-1] for r in p.interiors],
                          area=Area(value=p.area, source="inferred"), label_sources=[_ref(e)]))
    ceiling = None
    if heights and max(heights) > 0:
        ceiling = _m(max(heights))
    else:
        ctx.issue("ifc_ceiling_height_missing", f"storey {st.Name or st.GlobalId} has no IfcSpace: no ceiling "
                  "height is known and none is assumed", [st])
    cols = [c for e in of("IfcColumn") if (c := _column(ctx, e, finished)) is not None]
    stairs = [c for e in of("IfcStair") if (c := _stair(ctx, e)) is not None]
    roof_models = [c for e in roofs if (c := _roof(ctx, e)) is not None]
    for lst, pre in ((cols, "column"), (stairs, "stair"), (roof_models, "roof")):
        for n, x in enumerate(lst, 1):
            lst[n - 1] = x.model_copy(update={"id": f"{pre}-{n:03d}"})
    return Floor(id=fid, name=name, elevation=Measured(value=elev, source=src), ceiling_height=ceiling,
                 walls=wall_models, openings=openings, slabs=slab_models, rooms=rooms, columns=cols,
                 stairs=stairs, roofs=roof_models)


def _openings(ctx: _Ctx, els, wall_of, finished, walls, wall_models) -> list[Opening]:
    kept: list[Opening] = []
    cand = []
    for e in els:
        if not (e.is_a("IfcDoor") or e.is_a("IfcWindow")):
            continue
        hole = next((r.RelatingOpeningElement for r in getattr(e, "FillsVoids", [])), None)
        host = next((r.RelatingBuildingElement for r in hole.VoidsElements), None) if hole is not None else None
        w = wall_of.get(host.id()) if host is not None else None
        if w is None:
            ctx.issue("ifc_opening_no_host", f"{e.is_a()} {e.GlobalId} is not in an opening of an imported wall; "
                      "not imported", [e])
            continue
        mv = ctx.mesh(e)
        if mv is None:
            continue
        cand.append((e, w, mv[0]))
    for e, w, v in cand:
        axis = _axis(w.centreline)
        if axis is None:
            ctx.issue("ifc_opening_not_axis_aligned", f"{e.is_a()} {e.GlobalId} sits in a wall that is not "
                      "axis-aligned; openings need an axis-aligned wall, not imported", [e])
            continue
        c = w.centreline
        u = v[:, axis] - c.start[axis]
        lo, hi = max(float(u.min()), 0.0), min(float(u.max()), math.dist(c.start, c.end))
        a = [c.start[0], c.start[1]]
        b = list(a)
        a[axis], b[axis] = c.start[axis] + lo, c.start[axis] + hi
        door = e.is_a("IfcDoor")
        height = float(v[:, 2].max() - v[:, 2].min())
        sill = float(v[:, 2].min()) - finished
        try:
            o = Opening(
                id=f"opening-{len(kept) + 1:03d}", kind="door" if door else "window", wall_id=w.id,
                span=LineGeometry(start=tuple(a), end=tuple(b)), offset=_m(lo, "inferred"),
                width=_m(hi - lo), height=_m(height), sill_height=_m(max(sill, 0.0) if sill > -ctx.s.ifc_snap_mm else sill),
                sources=[_ref(e)], detail=_detail(hi - lo, height, door, ctx.s))
            Floor(id="check", name="check", elevation=_m(0), walls=wall_models, openings=[*kept, o])
        except (ValueError, ValidationError) as err:
            ctx.issue("ifc_opening_invalid", f"{e.is_a()} {e.GlobalId} does not fit its wall ({"; ".join(str(err).splitlines()[1::2])[:200]}); "
                      "not imported", [e])
            continue
        kept.append(o)
    kept.sort(key=lambda o: (o.span.start[1], o.span.start[0]))
    return [o.model_copy(update={"id": f"opening-{n:03d}"}) for n, o in enumerate(kept, 1)]


def _detail(width: float, height: float, door: bool, s: Settings) -> OpeningDetail | None:
    """Nominal frame + panel (never in an IFC opening), same rule as the DXF reader."""
    fw = s.opening_frame_width_mm
    if width <= 2 * fw or height <= (fw if door else 2 * fw):
        return None
    return OpeningDetail(
        frame_width=Measured(value=fw, source="defaulted"), panel="leaf" if door else "glass",
        panel_thickness=Measured(value=s.door_leaf_thickness_mm if door else s.window_glass_thickness_mm,
                                 source="defaulted"))


def _column(ctx: _Ctx, e, finished: float) -> Column | None:
    fp = ctx.footprint(e)
    if fp is None:
        return None
    p, z0, z1 = fp
    if z1 - z0 <= 0:
        ctx.issue("ifc_column_no_height", f"IfcColumn {e.GlobalId} has no height; not imported", [e])
        return None
    cx, cy = p.centroid.x, p.centroid.y
    r = max(math.dist((cx, cy), q) for q in p.exterior.coords)
    if p.area >= ctx.s.ifc_circle_fill * math.pi * r * r:
        return Column(id="column-0", shape="circle", centre=(cx, cy), radius=_m(r, "inferred"),
                      height=_m(z1 - z0), sources=[_ref(e)])
    c = _rect_axes(p, ctx.s.ifc_snap_mm)
    if p.area < ctx.s.ifc_rect_fill * math.dist(c[0], c[1]) * math.dist(c[1], c[2]):
        ctx.issue("ifc_column_approximated", f"IfcColumn {e.GlobalId} is neither a rectangle nor a circle in "
                  "plan; imported as its bounding rectangle", [e])
    return Column(id="column-0", shape="rect", polygon=c, height=_m(z1 - z0), sources=[_ref(e)])


def _stair(ctx: _Ctx, e) -> Stair | None:
    mv = ctx.mesh(e)
    fp = ctx.footprint(e)
    if mv is None or fp is None:
        return None
    v = mv[0]
    tol = ctx.s.ifc_snap_mm
    x0, y0, x1, y1 = fp[0].bounds
    poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    base = Stair(id="stair-0", polygon=poly, sources=[_ref(e)])
    axis = 0 if x1 - x0 >= y1 - y0 else 1
    z0 = float(v[:, 2].min())
    levels = sorted({round(float(z) / tol) * tol for z in v[:, 2] if z > z0 + tol})
    if not levels:
        ctx.issue("ifc_stair_steps_unreadable", f"IfcStair {e.GlobalId} has no readable steps; imported as "
                  "its footprint only", [e])
        return base
    rise = levels[0] - z0
    if any(abs((b - a) - rise) > 2 * tol for a, b in zip([z0, *levels], levels, strict=False)):
        ctx.issue("ifc_stair_steps_unreadable", f"IfcStair {e.GlobalId} has uneven steps (not a straight "
                  "block stair); imported as its footprint only", [e])
        return base
    top = v[v[:, 2] >= levels[-1] - tol][:, axis]
    lo, hi = (x0, x1) if axis == 0 else (y0, y1)
    sign = 1 if float(top.mean()) > (lo + hi) / 2 else -1
    n = len(levels) + 1
    return Stair(id="stair-0", polygon=poly, direction=("+" if sign > 0 else "-") + "xy"[axis],
                 total_rise=_m(n * rise, "inferred"), riser_count=n, riser_height=_m(rise, "inferred"),
                 tread_depth=_m((hi - lo) / len(levels), "inferred"), sources=[_ref(e)])


def _roof(ctx: _Ctx, e) -> Roof | None:
    fp = ctx.footprint(e)
    if fp is None:
        return None
    p, z0, z1 = fp
    kind = {"FLAT_ROOF": "flat", "GABLE_ROOF": "gable", "HIP_ROOF": "hip"}.get(e.PredefinedType)
    if kind is None and e.is_a("IfcSlab"):
        kind = "flat"  # an IfcSlab ROOF is a flat roof slab
    if kind is None:
        ctx.issue("ifc_roof_unclassified", f"IfcRoof {e.GlobalId} has type {e.PredefinedType}; only "
                  "FLAT_ROOF, GABLE_ROOF and HIP_ROOF are imported", [e])
        return None
    if kind == "flat":
        return Roof(id="roof-0", kind="flat", requested="flat", polygon=list(p.exterior.coords)[:-1],
                    outline_source="roof_layer", base_elevation=_m(z0), thickness=_m(z1 - z0),
                    sources=[_ref(e)])
    x0, y0, x1, y1 = p.bounds
    v = ctx.mesh(e)[0]
    top = v[v[:, 2] >= z1 - ctx.s.ifc_snap_mm]
    along_x = np.ptp(top[:, 0]) >= np.ptp(top[:, 1])
    half_span = min(x1 - x0, y1 - y0) / 2
    return Roof(id="roof-0", kind=kind, requested=kind, polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                outline_source="roof_layer", base_elevation=_m(z0), overhang=_m(0.0, "inferred"),
                pitch=Param(value=math.degrees(math.atan2(z1 - z0, half_span)), unit="deg", source="inferred"),
                ridge_axis="x" if along_x else "y", ridge_height=_m(z1 - z0, "inferred"), sources=[_ref(e)])

