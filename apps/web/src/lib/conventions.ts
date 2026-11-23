import { API_BASE, send, type Issue } from "./api";
import type { FloorCandidate } from "./split";

// Layer conventions (06): a preset plus the user's layer -> role mapping. The role names and the
// preset tables come from the API (GET /conventions); nothing about layer naming lives here.
export type ConventionsSpec = { preset: string; mapping: Record<string, string> };
export const DEFAULT_CONVENTIONS: ConventionsSpec = { preset: "aia", mapping: {} };
export type PresetInfo = { id: string; label: string; source: string; layers: Record<string, string> };
export type LayerRole = { layer: string; role: string | null; entities: number };
export type LayerInfo = { layers: LayerRole[]; issues: Issue[]; needs: "units"[]; floor_candidates: FloorCandidate[] };
type Fetch = typeof fetch;

const url = (p: string) => `${API_BASE}/api/v1${p}`;
const req = <T,>(method: string, path: string, f: Fetch, body?: unknown) =>
  send<T>(() =>
    f(url(path), {
      method,
      credentials: "include",
      ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    }),
  );

export const listConventions = (f: Fetch = fetch) => req<{ roles: string[]; presets: PresetInfo[] }>("GET", "/conventions", f);
// `units`: the unit the user chose for the drawing (it replaces a wrong header), so the preflight reads it that way
export const inspectLayers = (uploadId: string, spec: ConventionsSpec, f: Fetch = fetch, units?: string) =>
  req<LayerInfo>("POST", `/uploads/${uploadId}/layers${units ? `?units=${encodeURIComponent(units)}&units_override=true` : ""}`, f, spec);
export const getProjectConventions = (pid: string, f: Fetch = fetch) => req<ConventionsSpec>("GET", `/projects/${pid}/conventions`, f);
export const putProjectConventions = (pid: string, spec: ConventionsSpec, f: Fetch = fetch) =>
  req<ConventionsSpec>("PUT", `/projects/${pid}/conventions`, f, spec);
