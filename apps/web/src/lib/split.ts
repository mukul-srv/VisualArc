import type { GenerationParams, Preflight } from "./api";
import { buildRequest, type FormValues } from "./params";

// Pure helpers for the consolidated-DXF split step. The engine proposes the floors;
// nothing here detects or interprets geometry.
export type FloorCandidate = {
  key: string;
  bbox: { min: [number, number]; max: [number, number] };
  entity_counts: Record<string, number>;
  proposed_offset: { x: number; y: number; source: "inferred" };
};

export type SplitRow = { key: string; exclude: boolean; name: string; elevation: string; offsetX: string; offsetY: string };

export const bboxSize = (c: FloorCandidate) => ({
  width: c.bbox.max[0] - c.bbox.min[0],
  height: c.bbox.max[1] - c.bbox.min[1],
});

/** Offsets are prefilled from the engine's proposal (shown as "proposed"); the elevation
 *  is never guessed. The key is only a suggested name. */
export const initialRows = (cs: FloorCandidate[]): SplitRow[] =>
  cs.map((c) => ({
    key: c.key,
    exclude: false,
    name: c.key,
    elevation: "",
    offsetX: String(c.proposed_offset.x),
    offsetY: String(c.proposed_offset.y),
  }));

export type SplitBody = Omit<GenerationParams, "upload_id"> & {
  project_name: string;
  floors: (
    | { key: string; exclude: true }
    | { key: string; exclude: false; name: string; elevation: number; offset_x: number; offset_y: number }
  )[];
};

const finite = (t: string) => t.trim() !== "" && Number.isFinite(Number(t));

/** Validates everything the server also checks, so mistakes are caught before the round trip. */
export function buildSplitRequest(
  pre: Preflight,
  form: FormValues,
  rows: SplitRow[],
  projectName: string,
): { ok: true; body: SplitBody } | { ok: false; errors: string[] } {
  // a consolidated file stops at the split, so preflight reports no wall/ceiling "needs": require both here
  const needs: Preflight["needs"] = [...new Set<Preflight["needs"][number]>([...pre.needs, "wall_height", "ceiling_height"])];
  const base = buildRequest({ ...pre, needs }, form);
  const errors = base.ok ? [] : [...base.errors];
  if (!projectName.trim()) errors.push("Project name is required.");
  const kept = rows.filter((r) => !r.exclude);
  if (!kept.length) errors.push("Build at least one floor.");
  for (const r of kept) {
    if (!r.name.trim()) errors.push(`${r.key}: floor name is required.`);
    if (!finite(r.elevation)) errors.push(`${r.key}: elevation (mm) must be a number.`);
    if (!finite(r.offsetX) || !finite(r.offsetY)) errors.push(`${r.key}: offsets (mm) must be numbers.`);
  }
  const names = kept.map((r) => r.name.trim().toLowerCase());
  if (new Set(names).size < names.length) errors.push("Floor names must be unique.");
  const elevs = kept.filter((r) => finite(r.elevation)).map((r) => Number(r.elevation));
  if (new Set(elevs).size < elevs.length) errors.push("Floor elevations must be unique.");
  if (errors.length || !base.ok) return { ok: false, errors };
  const params: Partial<GenerationParams> = { ...base.params };
  delete params.upload_id; // the URL names the upload
  return {
    ok: true,
    body: {
      ...params,
      project_name: projectName.trim(),
      floors: rows.map((r) =>
        r.exclude
          ? { key: r.key, exclude: true as const }
          : {
              key: r.key,
              exclude: false as const,
              name: r.name.trim(),
              elevation: Number(r.elevation),
              offset_x: Number(r.offsetX),
              offset_y: Number(r.offsetY),
            },
      ),
    },
  };
}
