import type { BuildingType, GenerationParams, Issue, Preflight } from "./api";

export const UNITS = ["mm", "cm", "m", "in", "ft"] as const;

export const BUILDING_TYPES: readonly BuildingType[] = ["residential", "commercial"];

// Empty height fields mean "use the preset"; the backend tags those values as assumed.
export type FormValues = {
  buildingType: BuildingType;
  wallHeight: string;
  ceilingHeight: string;
  units: string;
  doorHeight: string;
  windowHeight: string;
  windowSill: string;
};

export const splitIssues = (issues: Issue[]) => ({
  blocking: issues.filter((i) => i.severity === "blocking"),
  warnings: issues.filter((i) => i.severity === "warning"),
});

function num(text: string, label: string, min: "positive" | "nonneg", errors: string[]): number | undefined {
  if (text.trim() === "") return undefined;
  const v = Number(text);
  if (!Number.isFinite(v) || (min === "positive" ? v <= 0 : v < 0)) {
    errors.push(`${label} must be a ${min === "positive" ? "positive" : "non-negative"} number (mm)`);
    return undefined;
  }
  return v;
}

/** Validates what the user typed. Empty fields are omitted: the backend fills them from the
 *  building-type preset and says so; only units (never defaultable) are required. */
export function buildRequest(
  pre: Preflight,
  f: FormValues,
): { ok: true; params: GenerationParams } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  const wall_height = num(f.wallHeight, "Wall height", "positive", errors);
  const ceiling_height = num(f.ceilingHeight, "Ceiling height", "positive", errors);
  if (pre.needs.includes("units") && !f.units) errors.push("Drawing units are required (the DXF has none)");
  if (f.units && !(UNITS as readonly string[]).includes(f.units)) errors.push("Unknown units");
  const door_height = num(f.doorHeight, "Door height", "positive", errors);
  const window_height = num(f.windowHeight, "Window height", "positive", errors);
  const window_sill = num(f.windowSill, "Window sill", "nonneg", errors);
  if (errors.length) return { ok: false, errors };
  const params: GenerationParams = { upload_id: pre.upload_id, building_type: f.buildingType };
  const set = { wall_height, ceiling_height, units: f.units || undefined, door_height, window_height, window_sill };
  for (const [k, v] of Object.entries(set)) if (v !== undefined) (params as Record<string, unknown>)[k] = v;
  return { ok: true, params };
}
