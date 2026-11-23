// Selection logic, free of three.js/DOM so it is unit-testable. Input is the GLB node's
// `userData` (the canonical element's fields, written by the API exporter) and nothing
// else: every displayed value and provenance comes straight from that element, never
// from a default or another element.

export type Provenance = "source_extracted" | "user_provided" | "defaulted" | "inferred";
export type Measured = { value: number; unit: string; source: Provenance };
export type SourceRef = { layer: string; entity_handle: string };
type Pt = [number, number];

export type OpeningData = {
  id: string;
  kind: "door" | "window";
  wall_id: string;
  span: { start: Pt; end: Pt };
  offset: Measured;
  width: Measured;
  height: Measured;
  sill_height: Measured;
  sources: SourceRef[];
  swing?: { hinge: "start" | "end"; opens_toward: "+x" | "-x" | "+y" | "-y"; source: SourceRef } | null; // doors
  detail?: { frame_width: Measured; panel: "leaf" | "glass"; panel_thickness: Measured } | null;
};

export type Area = { value: number; unit: "mm2"; source: Provenance };
export type RoomData = { id: string; name: string; name_source: Provenance; area: Area; label_sources: SourceRef[] };

export type ElementData = {
  id: string;
  type: "wall" | "junction" | "floor_boundary" | "slab" | "column" | "balcony" | "balcony_railing" | "stair" | "ramp" | "roof" | "ceiling" | "opening_part";
  floor_id?: string;
  thickness?: Measured;
  height?: Measured | null; // wall height; for a ceiling, the ceiling-height parameter
  role?: "exterior" | "interior" | null; // wall; absent in pre-0.4.0 GLBs
  role_source?: Provenance | null;
  wall_ids?: string[];
  source?: Provenance; // junction: always "inferred"
  elevation?: Measured; // ceiling: floor elevation + ceiling height
  boundary_id?: string | null; // slab: the floor boundary it sits under
  floor_offset_mm?: number; // wall: its base to the finished floor (the slab thickness); openings count from there
  shape?: "rect" | "circle"; // column
  centre?: Pt;
  radius?: Measured | null;
  railing_height?: Measured | null; // balcony
  railing_thickness?: Measured | null;
  balcony_id?: string; // balcony_railing
  direction?: string | null; // stair, ramp: towards the top
  kind?: "flat" | "gable" | "hip"; // roof: what was built
  requested?: "flat" | "gable" | "hip"; // roof: what the parameters asked for
  outline_source?: "roof_layer" | "walls";
  base_elevation?: Measured | null;
  overhang?: Measured | null;
  pitch?: { value: number; unit: string; source: Provenance } | null;
  ridge_axis?: "x" | "y" | null;
  ridge_height?: Measured | null;
  type_param?: { value: number | string; unit: string; source: Provenance } | null;
  total_rise?: Measured | null; // stair
  rise_param?: Measured | null;
  run_param?: Measured | null;
  riser_count?: number | null;
  riser_height?: Measured | null;
  tread_depth?: Measured | null;
  rise?: Measured | null; // ramp
  slope?: number | null;
  sources?: SourceRef[];
  openings?: OpeningData[];
  opening?: OpeningData; // opening_part: the opening this frame/leaf/glass belongs to
  part?: "frame" | "leaf" | "glass";
};

export const PROVENANCE_LABEL: Record<Provenance, string> = {
  source_extracted: "extracted from DXF",
  user_provided: "user-specified",
  defaulted: "ASSUMED DEFAULT (not in the drawing)",
  inferred: "INFERRED (not drawn)",
};

export type Row = { label: string; value: string; provenance?: Provenance };
export type Panel = { title: string; id: string; rows: Row[]; sourcesLabel: string; sources: string[] };

const mm = (v: number) => `${Number(v.toFixed(3))} mm`;
const measured = (label: string, m: Measured | null | undefined): Row =>
  m ? { label, value: mm(m.value), provenance: m.source } : { label, value: "not set" };
export const refs = (s: SourceRef[] | undefined) => (s ?? []).map((r) => `${r.layer}:${r.entity_handle}`);

/** Which opening, if any, a click on a host wall landed in (wall bore or reveal surface).
 *  `hit` is the three.js world point in metres (Y up, plan y -> -z); `baseY` the wall's
 *  lowest point (floor elevation) in metres. Tolerance 1.5 mm covers reveal surfaces. */
export function pickOpening(
  ud: ElementData,
  hit: { x: number; y: number; z: number },
  baseY: number,
): OpeningData | null {
  const px = hit.x * 1000;
  const py = -hit.z * 1000;
  const h = (hit.y - baseY) * 1000;
  const eps = 1.5;
  for (const o of ud.openings ?? []) {
    const alongX = Math.abs(o.span.end[0] - o.span.start[0]) >= Math.abs(o.span.end[1] - o.span.start[1]);
    const axis = alongX ? 0 : 1;
    const a = alongX ? px : py;
    const lo = Math.min(o.span.start[axis], o.span.end[axis]);
    const hi = Math.max(o.span.start[axis], o.span.end[axis]);
    const sill = o.sill_height.value;
    if (a >= lo - eps && a <= hi + eps && h >= sill - eps && h <= sill + o.height.value + eps) return o;
  }
  return null;
}

export function describeOpening(o: OpeningData): Panel {
  return {
    title: o.kind === "door" ? "Door opening" : "Window opening",
    id: o.id,
    rows: [
      { label: "Host wall", value: o.wall_id },
      measured("Offset along host", o.offset),
      measured("Width", o.width),
      measured("Height", o.height),
      measured("Sill height", o.sill_height),
      ...(o.kind === "door"
        ? [
            o.swing
              ? { label: "Swing", value: `hinge at span ${o.swing.hinge}, opens toward ${o.swing.opens_toward} (leaf drawn closed)`, provenance: "source_extracted" as const }
              : { label: "Swing", value: "not set (no swing arc found in the drawing)" },
          ]
        : []),
      ...(o.detail
        ? [
            measured("Frame width", o.detail.frame_width),
            measured(o.detail.panel === "leaf" ? "Leaf thickness" : "Glass thickness", o.detail.panel_thickness),
          ]
        : [{ label: "Frame and panel", value: "not modelled (opening too small)" }]),
    ],
    sourcesLabel: "Source entities (marker first, then jamb lines, then swing arc)",
    sources: [...refs(o.sources), ...(o.swing ? refs([o.swing.source]) : [])],
  };
}

/** Square metres with the provenance; the canonical value stays in mm2. */
export const m2 = (a: Area) => `${(a.value / 1e6).toFixed(2)} m²`;

export function describeRoom(r: RoomData, floorId?: string): Panel {
  return {
    title: "Room",
    id: r.id,
    rows: [
      ...(floorId ? [{ label: "Floor", value: floorId }] : []),
      { label: "Name", value: r.name, provenance: r.name_source },
      { label: "Area (inner wall faces)", value: m2(r.area), provenance: r.area.source },
    ],
    sourcesLabel: "Label entities (first names the room)",
    sources: refs(r.label_sources),
  };
}

export function describeElement(ud: ElementData): Panel {
  const where: Row[] = ud.floor_id ? [{ label: "Floor", value: ud.floor_id }] : [];
  if (ud.type === "column") {
    return {
      title: "Column",
      id: ud.id,
      rows: [
        ...where,
        { label: "Shape", value: ud.shape === "circle" ? "circle" : "rectangle" },
        ...(ud.shape === "circle" ? [measured("Radius", ud.radius)] : []),
        measured("Height (ceiling-height parameter)", ud.height),
      ],
      sourcesLabel: "Source entity (column layer)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "balcony") {
    return {
      title: "Balcony / terrace",
      id: ud.id,
      rows: [
        ...where,
        measured("Slab thickness", ud.thickness),
        measured("Railing height", ud.railing_height),
        measured("Railing thickness", ud.railing_thickness),
      ],
      sourcesLabel: "Source entity (balcony layer)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "roof") {
    return {
      title: "Roof",
      id: ud.id,
      rows: [
        ...where,
        { label: "Type", value: ud.kind ?? "", provenance: ud.type_param?.source },
        ...(ud.requested && ud.requested !== ud.kind ? [{ label: "Requested type", value: `${ud.requested} (not possible here, see issues)` }] : []),
        ud.pitch ? { label: "Pitch", value: `${ud.pitch.value} deg`, provenance: ud.pitch.source } : { label: "Pitch", value: "not used (flat)" },
        measured("Base elevation (top of walls)", ud.base_elevation),
        ...(ud.ridge_height ? [measured("Ridge height above the base", ud.ridge_height), { label: "Ridge runs along", value: ud.ridge_axis ?? "" }] : []),
        ...(ud.overhang ? [measured("Eave overhang", ud.overhang)] : []),
        ...(ud.thickness ? [measured("Slab thickness", ud.thickness)] : []),
        { label: "Outline from", value: ud.outline_source === "roof_layer" ? "roof-plan layer" : "walls" },
      ],
      sourcesLabel: "Source entities (roof-plan outline)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "stair") {
    return {
      title: "Stair",
      id: ud.id,
      rows: [
        ...where,
        { label: "Direction (towards the top)", value: ud.direction ?? "not set (no usable arrow line)" },
        measured("Total rise (storey height + slab)", ud.total_rise),
        measured("Target riser height (parameter)", ud.rise_param),
        measured("Target tread depth (parameter)", ud.run_param),
        ud.riser_count ? { label: "Risers", value: `${ud.riser_count} (${ud.riser_count - 1} treads)` } : { label: "Steps", value: "not built (see issues)" },
        measured("Riser height", ud.riser_height),
        measured("Tread depth (from the drawing)", ud.tread_depth),
      ],
      sourcesLabel: "Source entities (outline, then arrow line)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "ramp") {
    return {
      title: "Ramp",
      id: ud.id,
      rows: [
        ...where,
        { label: "Direction (towards the top)", value: ud.direction ?? "not set (no usable arrow line)" },
        measured("Rise (storey height + slab)", ud.rise),
        measured("Slab thickness", ud.thickness),
        { label: "Slope", value: ud.slope == null ? "not built (see issues)" : `${(ud.slope * 100).toFixed(1)} % (1:${(1 / ud.slope).toFixed(1)})` },
      ],
      sourcesLabel: "Source entities (outline, then arrow line)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "balcony_railing") {
    return {
      title: "Balcony railing",
      id: ud.id,
      rows: [...where, { label: "Balcony", value: ud.balcony_id ?? "" }, measured("Height", ud.height), measured("Thickness", ud.thickness)],
      sourcesLabel: "Source entity (balcony outline)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "opening_part" && ud.opening) return describeOpening(ud.opening);
  const floor: Row[] = ud.floor_id ? [{ label: "Floor", value: ud.floor_id }] : [];
  if (ud.type === "wall") {
    const n = ud.openings?.length ?? 0;
    return {
      title: "Wall",
      id: ud.id,
      rows: [
        ...floor,
        measured("Thickness", ud.thickness),
        measured("Height", ud.height),
        ...(ud.role === undefined
          ? []
          : [
              ud.role
                ? { label: "Role", value: ud.role, provenance: ud.role_source ?? undefined }
                : { label: "Role", value: "unknown (conflicting layers)" },
            ]),
        { label: "Openings hosted", value: String(n) },
      ],
      sourcesLabel: "Source entities (two boundary lines)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "junction") {
    return {
      title: "Junction",
      id: ud.id,
      rows: [
        ...floor,
        { label: "Origin", value: "corner/T fill between walls", provenance: ud.source ?? "inferred" },
        { label: "Walls touched", value: (ud.wall_ids ?? []).join(", ") },
      ],
      sourcesLabel: "Source entities",
      sources: [], // not drawn in the DXF: derived from the walls above
    };
  }
  if (ud.type === "ceiling") {
    return {
      title: "Ceiling",
      id: ud.id,
      rows: [...floor, measured("Elevation", ud.elevation), ...(ud.height ? [measured("Ceiling height", ud.height)] : [])],
      sourcesLabel: "Source entities (floor boundary)",
      sources: refs(ud.sources),
    };
  }
  if (ud.type === "slab") {
    return {
      title: "Slab",
      id: ud.id,
      rows: [...floor, measured("Thickness", ud.thickness), { label: "Under", value: ud.boundary_id ?? "" }],
      sourcesLabel: "Source entities (floor boundary)",
      sources: refs(ud.sources),
    };
  }
  return {
    title: "Floor boundary",
    id: ud.id,
    rows: floor,
    sourcesLabel: "Source entities",
    sources: refs(ud.sources),
  };
}
