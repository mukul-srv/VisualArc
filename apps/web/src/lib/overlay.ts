import { API_BASE, send } from "./api";
import type { Underlay } from "./underlay";

// Plan overlay: the source drawing's linework (grey) under what the engine built (coloured), one floor.
// Everything is in the floor's plan millimetres; plan y points up, the screen's y down.
type Fetch = typeof fetch;
export type OverlayData = {
  floor_id: string;
  unit: "mm";
  source: { segments: { layer: string; wall: boolean; p: [number, number, number, number] }[]; total: number; truncated: boolean };
  model: {
    // handles, provenance, wall_id, width/height/sill and rooms come with the backend's editing support (older data lacks them)
    walls: { id: string; start: [number, number]; end: [number, number]; thickness: number; handles?: string[]; provenance?: string }[];
    junctions: [number, number][][];
    openings: { id: string; kind: string; start: [number, number]; end: [number, number]; inferred: boolean; wall_id?: string; width?: number; height?: number; sill?: number; provenance?: string; handles?: string[] }[];
    boundaries: { polygon: [number, number][]; inferred: boolean }[];
    rooms?: { id: string; polygon: [number, number][]; name: string; name_source: string; area: number; label_point: [number, number] }[];
  };
  edits?: unknown[]; // the floor's stored edit ops, in order
  underlay?: Underlay | null; // a floor made from an image to trace over
};

export const getPlanOverlay = (pid: string, floorId: string, f: Fetch = fetch, share?: string | null) =>
  send<{ overlay: OverlayData }>(async () => {
    const res = await f(`${API_BASE}/api/v1/projects/${pid}/floors/${floorId}/plan${share ? `?share=${encodeURIComponent(share)}` : ""}`, { credentials: "include" });
    return res.ok ? new Response(JSON.stringify({ overlay: await res.json() })) : res;
  });

export type Bounds = { minX: number; minY: number; maxX: number; maxY: number };
export type Fit = { scale: number; offX: number; offY: number; height: number };

/** Bounds of everything drawn (source and model), or null when there is nothing. */
export function overlayBounds(d: OverlayData): Bounds | null {
  const pts: [number, number][] = [
    ...d.source.segments.flatMap((s): [number, number][] => [[s.p[0], s.p[1]], [s.p[2], s.p[3]]]),
    ...d.model.walls.flatMap((w): [number, number][] => [w.start, w.end]),
    ...d.model.boundaries.flatMap((b) => b.polygon),
    ...d.model.openings.flatMap((o): [number, number][] => [o.start, o.end]),
  ];
  if (!pts.length) return null;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) };
}

/** Uniform scale and offsets fitting `b` into a width x height canvas with `pad` px around (never zero size). */
export function fit(b: Bounds, width: number, height: number, pad = 12): Fit {
  const w = Math.max(b.maxX - b.minX, 1), h = Math.max(b.maxY - b.minY, 1);
  const scale = Math.min((width - 2 * pad) / w, (height - 2 * pad) / h);
  return { scale, offX: pad - b.minX * scale + (width - 2 * pad - w * scale) / 2, offY: pad + b.maxY * scale + (height - 2 * pad - h * scale) / 2, height };
}

/** Plan mm -> canvas px (y flipped: plan up is screen up). */
export const toScreen = (f: Fit, x: number, y: number): [number, number] => [x * f.scale + f.offX, f.offY - y * f.scale];

/** Canvas px -> plan mm (the inverse of toScreen). */
export const toPlan = (f: Fit, sx: number, sy: number): [number, number] => [(sx - f.offX) / f.scale, (f.offY - sy) / f.scale];

/** Zoom by `factor` keeping the plan point under the cursor (sx, sy) where it is. */
export function zoomAt(f: Fit, sx: number, sy: number, factor: number): Fit {
  const [px, py] = toPlan(f, sx, sy);
  const scale = f.scale * factor;
  return { ...f, scale, offX: sx - px * scale, offY: sy + py * scale };
}

export const panBy = (f: Fit, dx: number, dy: number): Fit => ({ ...f, offX: f.offX + dx, offY: f.offY + dy });

/** A wall footprint rectangle (its four corners, plan mm) from its centreline and thickness. */
export function wallCorners(w: { start: [number, number]; end: [number, number]; thickness: number }): [number, number][] {
  const [x0, y0] = w.start, [x1, y1] = w.end, h = w.thickness / 2;
  const horizontal = Math.abs(y1 - y0) <= Math.abs(x1 - x0);
  return horizontal
    ? [[x0, y0 - h], [x1, y1 - h], [x1, y1 + h], [x0, y0 + h]]
    : [[x0 - h, y0], [x1 - h, y1], [x1 + h, y1], [x0 + h, y0]];
}

export const LEGEND = [
  { key: "source", label: "Source lines (other layers)", color: "#b8b8b8" },
  { key: "sourceWall", label: "Source lines (wall layers)", color: "#777777" },
  { key: "walls", label: "Built walls", color: "#d9534f" },
  { key: "openings", label: "Openings (dashed: inferred)", color: "#2e9e44" },
  { key: "boundary", label: "Floor boundary (dashed: inferred)", color: "#2a6fdb" },
] as const;
