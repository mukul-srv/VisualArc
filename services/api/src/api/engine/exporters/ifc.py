"""Canonical floors -> IFC4 (IfcOpenShell, used as a library only; it is LGPL).

One IfcProject > IfcSite > IfcBuilding > IfcBuildingStorey per floor, millimetres (the canonical unit),
plan X/Y/Z-up (no axis swap). Typed elements carry extruded-solid geometry from the canonical model
(ramps and pitched roofs: a faceted solid, they are not prisms). Names and provenance ride as the
`VisualArc_Provenance` property set (`*_source` per measured value, `AssumedDefaults`, `Sources`).
Anything that has no solid or no IFC type here becomes an IfcBuildingElementProxy (a footprint curve
when it has no volume) plus an entry in the returned issues and the project's `VisualArc_Export` set.
"""

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.guid
from shapely.geometry import LineString, Point, Polygon

from api.engine.canonical.model import Floor, Project
from api.engine.geometry3d.extrude import _flight_frame, build_ramp, build_roof
from api.engine.settings import DEFAULTS


def _props(dump: dict) -> dict:
    """Flatten a model dump: scalars as they are, Measured/Param/Area as `<k>_<unit>` + `<k>_source`."""
    out, defaulted = {}, []
    for k, v in dump.items():
        if k in ("id", "type", "sources"):
            continue
        if isinstance(v, dict) and "value" in v and "source" in v:
            out[f"{k}_{v.get('unit', 'none')}"] = v["value"]
            out[f"{k}_source"] = v["source"]
            if v["source"] == "defaulted":
                defaulted.append(k)
        elif isinstance(v, (str, int, float, bool)):
            out[k] = v
    if defaulted:
        out["AssumedDefaults"] = ", ".join(defaulted)
    srcs = dump.get("sources") or []
    if srcs:
        out["Sources"] = "; ".join(f"{s['format']}:{s['layer']}:{s['entity_handle']}" for s in srcs)
    return out


class _Builder:
    def __init__(self, project: Project):
        self.f = f = ifcopenshell.api.project.create_file(version="IFC4")
        self.issues: list[dict] = []
        self.root = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=project.id)
        ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "MILLIMETRE"})
        model = ifcopenshell.api.context.add_context(f, context_type="Model")
        self.body = ifcopenshell.api.context.add_context(
            f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
        plan = ifcopenshell.api.context.add_context(f, context_type="Plan")
        self.foot = ifcopenshell.api.context.add_context(
            f, context_type="Plan", context_identifier="FootPrint", target_view="PLAN_VIEW", parent=plan)
        self.site = self._spatial("IfcSite", "Site", self.root, None)
        self.building = self._spatial("IfcBuilding", "Building", self.site, self.site.ObjectPlacement)

    def _place(self, rel, xyz=(0.0, 0.0, 0.0)):
        f = self.f
        return f.createIfcLocalPlacement(rel, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(xyz)))

    def _spatial(self, cls, name, parent, rel_placement, xyz=(0.0, 0.0, 0.0)):
        e = ifcopenshell.api.root.create_entity(self.f, ifc_class=cls, name=name)
        e.ObjectPlacement = self._place(rel_placement, xyz)
        ifcopenshell.api.aggregate.assign_object(self.f, products=[e], relating_object=parent)
        return e

    def pset(self, e, props: dict, name="VisualArc_Provenance"):
        if props:
            p = ifcopenshell.api.pset.add_pset(self.f, product=e, name=name)
            ifcopenshell.api.pset.edit_pset(self.f, pset=p, properties=props)

    def _pt2(self, p):
        return self.f.createIfcCartesianPoint((float(p[0]), float(p[1])))

    def extrude(self, shape: Polygon, z0: float, depth: float):
        f = self.f

        def loop(ring):  # shapely rings are closed already
            return f.createIfcPolyline([self._pt2(p) for p in ring.coords])

        if shape.interiors:
            prof = f.createIfcArbitraryProfileDefWithVoids(
                "AREA", None, loop(shape.exterior), [loop(i) for i in shape.interiors])
        else:
            prof = f.createIfcArbitraryClosedProfileDef("AREA", None, loop(shape.exterior))
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z0))))
        return f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(depth))

    def brep(self, mesh):
        f = self.f
        pts = [f.createIfcCartesianPoint(tuple(float(c) for c in v)) for v in mesh.vertices]
        faces = [f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop([pts[i] for i in tri]), True)])
                 for tri in mesh.faces]
        return f.createIfcFacetedBrep(f.createIfcClosedShell(faces))

    def new(self, storey, cls, name, solids, props, predefined=None, kind="SweptSolid"):
        f = self.f
        e = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name, predefined_type=predefined)
        e.ObjectPlacement = self._place(storey.ObjectPlacement)
        e.Representation = f.createIfcProductDefinitionShape(
            None, None, [f.createIfcShapeRepresentation(self.body, "Body", kind, solids)])
        if cls == "IfcSpace":  # a spatial element: aggregated, not contained
            ifcopenshell.api.aggregate.assign_object(f, products=[e], relating_object=storey)
        elif cls != "IfcOpeningElement":  # an opening belongs to the wall it voids
            ifcopenshell.api.spatial.assign_container(f, products=[e], relating_structure=storey)
        self.pset(e, props)
        return e

    def proxy(self, storey, el_id, name, ring, props, code, why):
        """No volume or no IFC type: a proxy with its footprint curve (when there is one) + a recorded issue."""
        f = self.f
        e = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingElementProxy", name=name)
        e.ObjectPlacement = self._place(storey.ObjectPlacement)
        if ring:
            curve = f.createIfcPolyline([self._pt2(p) for p in [*ring, ring[0]]])
            e.Representation = f.createIfcProductDefinitionShape(
                None, None, [f.createIfcShapeRepresentation(self.foot, "FootPrint", "Curve2D", [curve])])
        ifcopenshell.api.spatial.assign_container(f, products=[e], relating_structure=storey)
        self.pset(e, {**props, "ExportIssue": f"{code}: {why}"})
        self.issues.append({"code": code, "element": el_id, "message": why})
        return e

    def floor(self, floor: Floor, offset: tuple[float, float]):
        storey = self._spatial("IfcBuildingStorey", floor.name, self.building, self.building.ObjectPlacement,
                               (float(offset[0]), float(offset[1]), 0.0))
        storey.Elevation = floor.elevation.value
        self.pset(storey, _props({"floor_id": floor.id, "elevation": floor.elevation.model_dump(),
                                  **({"ceiling_height": floor.ceiling_height.model_dump()}
                                     if floor.ceiling_height else {})}))
        base, z0 = floor.elevation.value, floor.finished_level_mm
        lift = z0 - base
        walls = {w.id: w for w in floor.walls}
        hosted: dict[str, list] = {}
        for o in floor.openings:
            hosted.setdefault(o.wall_id, []).append(o)

        def dump(el, *exclude):
            return _props(el.model_dump(
                mode="json", exclude={"centreline", "polygon", "holes", "railings", *exclude}))

        for w in floor.walls:
            t = w.thickness.value
            rect = LineString([w.centreline.start, w.centreline.end]).buffer(t / 2, cap_style="flat")
            wall = self.new(storey, "IfcWall", w.id, [self.extrude(rect, base, w.height.value + lift)],
                            dump(w), "STANDARD")
            for o in hosted.get(w.id, []):
                zs = z0 + o.sill_height.value
                line = LineString([o.span.start, o.span.end])
                hole = self.new(storey, "IfcOpeningElement", f"{o.id}-opening",
                                [self.extrude(line.buffer(t / 2, cap_style="flat"), zs, o.height.value)],
                                {}, "OPENING")
                ifcopenshell.api.feature.add_feature(self.f, feature=hole, element=wall)
                d = o.detail
                thick = (d.panel_thickness.value if d else
                         DEFAULTS.door_leaf_thickness_mm if o.kind == "door" else DEFAULTS.window_glass_thickness_mm)
                props = dump(o, "detail", "span", "swing")
                if d is None:  # the nominal leaf/glass thickness stands in: say so
                    props["AssumedDefaults"] = ", ".join(filter(None, [props.get("AssumedDefaults"), "panel_thickness"]))
                if o.swing:
                    props["swing_hinge"], props["swing_opens_toward"] = o.swing.hinge, o.swing.opens_toward
                e = self.new(storey, "IfcDoor" if o.kind == "door" else "IfcWindow", o.id,
                             [self.extrude(line.buffer(thick / 2, cap_style="flat"), zs, o.height.value)],
                             props, o.kind.upper())
                e.OverallHeight, e.OverallWidth = o.height.value, o.width.value
                self.f.createIfcRelFillsElement(ifcopenshell.guid.new(), None, None, None, hole, e)
        for j in floor.junctions:
            h = max(walls[i].height.value for i in j.wall_ids) + lift
            self.new(storey, "IfcWall", j.id, [self.extrude(Polygon(j.polygon), base, h)],
                     {"source": j.source, "wall_ids": ", ".join(j.wall_ids)}, "NOTDEFINED")
        for s in floor.slabs:
            t = s.thickness.value
            self.new(storey, "IfcSlab", s.id, [self.extrude(Polygon(s.polygon, s.holes), z0 - t, t)], dump(s), "FLOOR")
        for b in floor.boundaries:  # a zero-thickness surface: the slab is the solid
            self.proxy(storey, b.id, b.id, b.polygon, dump(b), "ifc_surface_proxy",
                       "floor boundary is a zero-thickness surface; kept as a footprint")
        for c in floor.ceilings:
            self.proxy(storey, c.id, c.id, c.polygon, dump(c), "ifc_surface_proxy",
                       "ceiling is a zero-thickness surface; kept as a footprint")
        for r in floor.rooms:
            if floor.ceiling_height is None:
                self.proxy(storey, r.id, r.name, r.polygon, dump(r, "label_sources"), "ifc_room_no_height",
                           "no ceiling height; space kept as a footprint")
                continue
            self.new(storey, "IfcSpace", r.name,
                     [self.extrude(Polygon(r.polygon, r.holes), z0, floor.ceiling_height.value)],
                     {**dump(r, "label_sources"), "room_id": r.id}, "INTERNAL")
        for c in floor.columns:
            if c.height is None:
                self.proxy(storey, c.id, c.id, c.polygon or [], dump(c), "ifc_no_height", "column has no height")
                continue
            foot = Polygon(c.polygon) if c.shape == "rect" else Point(c.centre).buffer(c.radius.value, quad_segs=16)
            self.new(storey, "IfcColumn", c.id, [self.extrude(foot, z0, c.height.value)], dump(c), "COLUMN")
        for b in floor.balconies:
            if b.thickness is None:
                self.proxy(storey, b.id, b.id, b.polygon, dump(b), "ifc_balcony_flat",
                           "balcony drawn as a flat surface (no thickness); kept as a footprint")
            else:
                t = b.thickness.value
                self.new(storey, "IfcSlab", b.id, [self.extrude(Polygon(b.polygon), z0 - t, t)], dump(b), "FLOOR")
            if not b.railings:
                continue
            if b.railing_height is None or b.railing_thickness is None:
                self.proxy(storey, f"{b.id}-railing", f"{b.id}-railing",
                           [p for r in b.railings for p in (r.start, r.end)], dump(b), "ifc_railing_no_size",
                           "railing height or thickness missing; kept as a footprint")
                continue
            solids = [self.extrude(LineString([r.start, r.end]).buffer(b.railing_thickness.value / 2, cap_style="flat"),
                                   z0, b.railing_height.value) for r in b.railings]
            self.new(storey, "IfcRailing", f"{b.id}-railing", solids,
                     {**dump(b), "balcony_id": b.id}, "HANDRAIL")
        for s in floor.stairs:
            if s.riser_count is None:
                self.proxy(storey, s.id, s.id, s.polygon, dump(s), "ifc_stair_no_steps",
                           "stair has no steps (direction or heights missing); kept as a footprint")
                continue
            axis, bottom, sign, n0, n1, _ = _flight_frame(s.polygon, s.direction)
            g, rh = s.tread_depth.value, s.riser_height.value
            solids = []
            for k in range(1, s.riser_count):  # same blocks as extrude.build_stair
                a, b = sorted((bottom + sign * (k - 1) * g, bottom + sign * k * g))
                ring = [(a, n0), (b, n0), (b, n1), (a, n1)] if axis == 0 else [(n0, a), (n1, a), (n1, b), (n0, b)]
                solids.append(self.extrude(Polygon(ring), z0, k * rh))
            self.new(storey, "IfcStair", s.id, solids, dump(s), "STRAIGHT_RUN_STAIR")
        for r in floor.ramps:
            mesh = build_ramp(r, z0)
            if mesh is None:
                self.proxy(storey, r.id, r.id, r.polygon, dump(r), "ifc_ramp_incomplete",
                           "ramp has no direction, rise or thickness; kept as a footprint")
                continue
            self.new(storey, "IfcRamp", r.id, [self.brep(mesh)], dump(r), "STRAIGHT_RUN_RAMP", kind="Brep")
        for r in floor.roofs:
            if r.base_elevation is None:
                self.proxy(storey, r.id, r.id, r.polygon, dump(r), "ifc_roof_no_base",
                           "roof has no base elevation (no walls); kept as a footprint")
            elif r.kind == "flat":
                self.new(storey, "IfcRoof", r.id,
                         [self.extrude(Polygon(r.polygon), r.base_elevation.value, r.thickness.value)],
                         dump(r), "FLAT_ROOF")
            else:
                self.new(storey, "IfcRoof", r.id, [self.brep(build_roof(r))], dump(r),
                         "GABLE_ROOF" if r.kind == "gable" else "HIP_ROOF", kind="Brep")


def build_ifc(floors: list[tuple[Project, tuple[float, float]]]) -> tuple[bytes, list[dict]]:
    """`floors`: (project, plan offset in mm) per project, in storey order. Returns (IFC bytes, issues)."""
    first = floors[0][0]
    b = _Builder(first)
    for project, off in floors:
        for building in project.buildings:
            for floor in building.floors:
                b.floor(floor, off)
    b.pset(b.root, {"schema_version": first.schema_version, "source_file": first.source_file,
                    "export_issue_count": len(b.issues),
                    **({"export_issues": "; ".join(f"{i['element']}: {i['code']}" for i in b.issues)}
                       if b.issues else {})},
           "VisualArc_Export")
    return b.f.to_string().encode(), b.issues
