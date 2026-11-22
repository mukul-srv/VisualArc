import type { Measured } from "./selection";

// Pure project helpers (no DOM/three.js). The manifest comes from GET /api/v1/projects/{id}.
export type Floor = { id: string; name: string; elevation: Measured; generation_id: string };
export type Manifest = { id: string; name: string; floors: Floor[] };

const HEX32 = /^[0-9a-f]{32}$/;
const PROVENANCES = ["source_extracted", "user_provided", "defaulted", "inferred"];

/** Validate an untrusted manifest; null when malformed (the viewer shows an error). */
export function parseManifest(x: unknown): Manifest | null {
  const m = x as Manifest | null;
  if (!m || typeof m.id !== "string" || typeof m.name !== "string" || !Array.isArray(m.floors)) return null;
  for (const f of m.floors) {
    if (
      !f ||
      typeof f.id !== "string" ||
      typeof f.name !== "string" ||
      !HEX32.test(f.generation_id) ||
      typeof f.elevation?.value !== "number" ||
      !PROVENANCES.includes(f.elevation.source)
    )
      return null;
  }
  return { id: m.id, name: m.name, floors: m.floors };
}

/** Lowest floor first; does not mutate the input. */
export const sortFloors = (floors: Floor[]): Floor[] =>
  [...floors].sort((a, b) => a.elevation.value - b.elevation.value);

export const viewerUrl = (projectId: string, floorId?: string, version?: number) =>
  `/viewer?project=${encodeURIComponent(projectId)}` +
  (floorId ? `&floor=${encodeURIComponent(floorId)}` : "") +
  (version ? `&version=${version}` : "");

/** The floor to show: the requested one if present, else the lowest. */
export const pickFloor = (m: Manifest, floorId: string | null): Floor | null =>
  m.floors.find((f) => f.id === floorId) ?? sortFloors(m.floors)[0] ?? null;
