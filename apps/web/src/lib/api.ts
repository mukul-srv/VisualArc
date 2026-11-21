import type { Floor } from "./project";
import type { SourceRef } from "./selection";
import type { FloorCandidate, SplitBody } from "./split";

// Thin client for the FastAPI backend. fetch is injectable so tests need no server.
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Issue = {
  code: string;
  severity: "blocking" | "warning";
  message: string;
  sources: SourceRef[];
};

export type Preflight = {
  upload_id: string;
  issues: Issue[];
  needs: ("wall_height" | "ceiling_height" | "units")[];
  inventory: { layers: string[]; entity_counts: Record<string, number> };
  floor_candidates?: FloorCandidate[]; // >= 2: the user must confirm the floors (split step)
};

export type GenerationParams = {
  upload_id: string;
  wall_height?: number;
  ceiling_height?: number;
  units?: string;
  door_height?: number;
  window_height?: number;
  window_sill?: number;
};

export type Failure = {
  ok: false;
  kind: "rejected" | "blocked" | "error";
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

async function send<T>(call: () => Promise<Response>): Promise<Result<T>> {
  let res: Response;
  try {
    res = await call();
  } catch {
    return {
      ok: false,
      kind: "error",
      message: `Cannot reach the API at ${API_BASE}. Is the backend running?`,
      issues: [],
    };
  }
  if (res.ok) return { ok: true, ...(await res.json()) };
  if (res.status === 409) {
    const body = await res.json();
    return { ok: false, kind: "blocked", message: body.detail, issues: body.issues ?? [] };
  }
  const kind = res.status === 422 || res.status === 413 ? "rejected" : "error";
  return { ok: false, kind, message: await detail(res), issues: [] };
}

export const uploadDxf = (file: Blob, f: Fetch = fetch) =>
  send<Preflight>(() =>
    f(`${API_BASE}/api/v1/uploads`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    }),
  );

export const generate = (params: GenerationParams, f: Fetch = fetch) =>
  send<{ generation_id: string; issues: Issue[] }>(() =>
    f(`${API_BASE}/api/v1/generations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  );

const post = (path: string, body: unknown, f: Fetch) =>
  f(`${API_BASE}/api/v1${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const createProject = (name: string, f: Fetch = fetch) =>
  send<{ project_id: string }>(() => post("/projects", { name }, f));

export type FloorParams = GenerationParams & { floor_name: string; elevation: number };
export const addFloor = (projectId: string, params: FloorParams, f: Fetch = fetch) =>
  send<{ floor: Floor; generation_id: string; issues: Issue[] }>(() =>
    post(`/projects/${projectId}/floors`, params, f),
  );

export const splitUpload = (uploadId: string, body: SplitBody, f: Fetch = fetch) =>
  send<{ project_id: string; floors: { key: string; floor: Floor; generation_id: string; issues: Issue[] }[]; issues: Issue[] }>(() =>
    post(`/uploads/${uploadId}/split`, body, f),
  );

export const getProject = (projectId: string, f: Fetch = fetch) =>
  send<{ manifest: unknown }>(async () => {
    const res = await f(`${API_BASE}/api/v1/projects/${projectId}`);
    // wrap so the shared `send` can spread it; the caller validates with parseManifest
    return res.ok ? new Response(JSON.stringify({ manifest: await res.json() })) : res;
  });

export const glbUrl = (generationId: string) =>
  `${API_BASE}/api/v1/generations/${generationId}/artifacts/glb`;
export const isGenerationId = (s: string) => /^[0-9a-f]{32}$/.test(s);
