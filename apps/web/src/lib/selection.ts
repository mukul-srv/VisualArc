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
};

export type ElementData = {
  id: string;
  type: "wall" | "junction" | "floor_boundary";
  floor_id?: string;
  thickness?: Measured;
  height?: Measured | null;
  wall_ids?: string[];
  source?: Provenance; // junction: always "inferred"
  sources?: SourceRef[];
  openings?: OpeningData[];
};

export const PROVENANCE_LABEL: Record<Provenance, string> = {
  source_extracted: "extracted from DXF",
  user_provided: "user-provided",
  defaulted: "DEFAULTED (assumed)",
  inferred: "INFERRED (not drawn)",
};

export type Row = { label: string; value: string; provenance?: Provenance };
export type Panel = { title: string; id: string; rows: Row[]; sourcesLabel: string; sources: string[] };

const mm = (v: number) => `${Number(v.toFixed(3))} mm`;
const measured = (label: string, m: Measured | null | undefined): Row =>
  m ? { label, value: mm(m.value), provenance: m.source } : { label, value: "not set" };
const refs = (s: SourceRef[] | undefined) => (s ?? []).map((r) => `${r.layer}:${r.entity_handle}`);

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
    ],
    sourcesLabel: "Source entities (marker first, then jamb lines)",
    sources: refs(o.sources),
  };
}

export function describeElement(ud: ElementData): Panel {
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
  return {
    title: "Floor boundary",
    id: ud.id,
    rows: floor,
    sourcesLabel: "Source entities",
    sources: refs(ud.sources),
  };
}
