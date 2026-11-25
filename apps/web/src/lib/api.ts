import type { Floor } from "./project";
import type { SourceRef } from "./selection";
import type { FloorCandidate, SplitBody } from "./split";

// Thin client for the FastAPI backend. fetch is injectable so tests need no server.
// Calls are same-origin (`/api/*`): next.config.ts rewrites them to NEXT_PUBLIC_API_URL, so
// the session cookie is first-party.
export const API_BASE = "";

export type Issue = {
  code: string;
  severity: "blocking" | "warning";
  message: string;
  sources: SourceRef[];
};

export type Preflight = {
  upload_id: string;
  issues: Issue[];
  needs: "units"[]; // only what can never be defaulted
  inventory: { layers: string[]; entity_counts: Record<string, number> };
  kind?: "ifc"; // an IFC upload: no layers or units; one floor per storey is made by importIfc
  storeys?: { key: string; name: string; elevation: number | null }[];
  floor_candidates?: FloorCandidate[]; // >= 2: the user must confirm the floors (split step)
};

export type BuildingType = "residential" | "commercial";
export type Preset = {
  wall_height: number;
  ceiling_height: number;
  door_height: number;
  window_height: number;
  window_sill: number;
  floor_to_floor: number;
  slab_thickness?: number;
  roof_type?: string;
  roof_pitch?: number;
  stair_rise?: number;
  stair_run?: number;
  lintel_height?: number;
  railing_height?: number;
};
export type Presets = Record<BuildingType, Preset>;

export type GenerationParams = {
  upload_id: string;
  building_type?: BuildingType; // missing heights come from this type's preset, tagged as assumed
  wall_height?: number;
  ceiling_height?: number;
  units?: string;
  units_override?: boolean; // the units replace a header the user says is wrong
  door_height?: number;
  window_height?: number;
  window_sill?: number;
  conventions?: { preset: string; mapping: Record<string, string> }; // default: the project's, else AIA
};

export type Failure = {
  ok: false;
  kind: "rejected" | "blocked" | "unauthorized" | "error";
  message: string;
  issues: Issue[];
};
export type Result<T> = ({ ok: true } & T) | Failure;
type Fetch = typeof fetch;

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return `server returned ${res.status}`;
}

export async function send<T>(call: () => Promise<Response>): Promise<Result<T>> {
  let res: Response;
  try {
    res = await call();
  } catch {
    return {
      ok: false,
      kind: "error",
      message: "Cannot reach the API. Is the backend running?",
      issues: [],
    };
  }
  if (res.ok) return { ok: true, ...(await res.json()) };
  if (res.status === 409) {
    const body = await res.json();
    return { ok: false, kind: "blocked", message: body.detail, issues: body.issues ?? [] };
  }
  const kind = res.status === 422 || res.status === 413 ? "rejected" : res.status === 401 ? "unauthorized" : "error";
  return { ok: false, kind, message: await detail(res), issues: [] };
}

export const uploadDxf = (file: Blob & { name?: string }, f: Fetch = fetch) =>
  send<Preflight>(() =>
    // the file name is only for display (the default name of a standalone model)
    f(`${API_BASE}/api/v1/uploads${file.name ? `?filename=${encodeURIComponent(file.name)}` : ""}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    }),
  );

/** An uploaded IFC as a project, one floor per storey (values come from the file). */
export const importIfc = (uploadId: string, projectName: string, f: Fetch = fetch) =>
  send<{ project_id: string; issues: Issue[] }>(() => post(`/uploads/${uploadId}/ifc`, { project_name: projectName }, f));

export const generate = (params: GenerationParams, f: Fetch = fetch) =>
  send<{ generation_id: string; issues: Issue[] }>(() =>
    f(`${API_BASE}/api/v1/generations`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  );

const post = (path: string, body: unknown, f: Fetch) =>
  f(`${API_BASE}/api/v1${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const createProject = (name: string, f: Fetch = fetch) =>
  send<{ project_id: string }>(() => post("/projects", { name }, f));

export type FloorParams = GenerationParams & { floor_name: string; elevation?: number }; // empty: assumed
export const addFloor = (projectId: string, params: FloorParams, f: Fetch = fetch) =>
  send<{ floor: Floor; generation_id: string; issues: Issue[] }>(() =>
    post(`/projects/${projectId}/floors`, params, f),
  );

export const splitUpload = (uploadId: string, body: SplitBody, f: Fetch = fetch) =>
  send<{ project_id: string; floors: { key: string; floor: Floor; generation_id: string; issues: Issue[] }[]; issues: Issue[] }>(() =>
    post(`/uploads/${uploadId}/split`, body, f),
  );

export const getPresets = (f: Fetch = fetch) =>
  send<{ presets: Presets }>(async () => {
    const res = await f(`${API_BASE}/api/v1/presets`, { credentials: "include" });
    return res.ok ? new Response(JSON.stringify({ presets: await res.json() })) : res;
  });

export const getProject = (projectId: string, f: Fetch = fetch, version?: number, share?: string | null) =>
  send<{ manifest: unknown }>(async () => {
    const q = new URLSearchParams();
    if (version !== undefined) q.set("version", String(version));
    if (share) q.set("share", share);
    const res = await f(`${API_BASE}/api/v1/projects/${projectId}${q.size ? `?${q}` : ""}`, { credentials: "include" });
    // wrap so the shared `send` can spread it; the caller validates with parseManifest
    return res.ok ? new Response(JSON.stringify({ manifest: await res.json() })) : res;
  });

export const glbUrl = (generationId: string, share?: string | null) =>
  `${API_BASE}/api/v1/generations/${generationId}/artifacts/glb${share ? `?share=${encodeURIComponent(share)}` : ""}`;
/** OBJ or IFC download of a project (all floors) or a standalone generation. */
export const exportUrl = (target: { project: string } | { generation: string }, fmt: "obj" | "ifc", share?: string | null) =>
  `${API_BASE}/api/v1/${"project" in target ? `projects/${target.project}` : `generations/${target.generation}`}/export/${fmt}${share ? `?share=${encodeURIComponent(share)}` : ""}`;
/** The canonical JSON of a generation, from its GLB url (same id, other artifact). */
export const canonicalUrl = (glb: string) => glb.replace("/artifacts/glb", "/artifacts/canonical");
export const isGenerationId = (s: string) => /^[0-9a-f]{32}$/.test(s);
