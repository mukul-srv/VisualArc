import type { ProjectParam } from "./projects";

export const PARAM_LABEL: Record<string, string> = {
  wall_height: "Wall height (mm): the room height you see",
  ceiling_height: "Ceiling height (mm): drawn only in walk mode",
  slab_thickness: "Slab thickness (mm)",
  roof_type: "Roof type",
  roof_pitch: "Roof pitch (degrees)",
  stair_rise: "Stair rise (mm)",
  stair_run: "Stair run (mm)",
  window_sill: "Window sill height (mm)",
  lintel_height: "Lintel (opening head) height (mm)",
  railing_height: "Railing height (mm)",
};
export const ROOF_TYPES = ["flat", "gable", "hip"];

const ZERO_OK = ["roof_pitch", "window_sill"]; // every other parameter must be > 0

/** Changes between the loaded parameters and the form text: a number/string to set, null (emptied
 *  user-specified field) to reset to the preset default. Untouched fields are omitted, so an
 *  assumed default stays assumed; errors name the bad fields. */
export function diffParameters(
  loaded: Record<string, ProjectParam>,
  text: Record<string, string>,
): { ok: true; values: Record<string, number | string | null> } | { ok: false; errors: string[] } {
  const values: Record<string, number | string | null> = {};
  const errors: string[] = [];
  for (const [k, p] of Object.entries(loaded)) {
    const t = (text[k] ?? "").trim();
    if (t === String(p.value)) continue;
    if (t === "") {
      if (p.source === "user_provided") values[k] = null;
      continue;
    }
    if (k === "roof_type") {
      values[k] = t;
      continue;
    }
    const v = Number(t);
    const bad = !Number.isFinite(v) || v < 0 || (v === 0 && !ZERO_OK.includes(k)) || (k === "roof_pitch" && v >= 90);
    if (bad) errors.push(`${PARAM_LABEL[k] ?? k} is not a valid number`);
    else values[k] = v;
  }
  return errors.length ? { ok: false, errors } : { ok: true, values };
}
