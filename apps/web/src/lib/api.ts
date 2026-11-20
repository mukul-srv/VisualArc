// Thin client for the FastAPI backend. fetch is injectable so tests need no server.
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Issue = {
  code: string;
  severity: "blocking" | "warning";
  message: string;
  sources: { layer: string; entity_handle: string }[];
};

export type Preflight = {
  upload_id: string;
  issues: Issue[];
  needs: ("wall_height" | "units")[];
  inventory: { layers: string[]; entity_counts: Record<string, number> };
};

export type GenerationParams = {
  upload_id: string;
  wall_height?: number;
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

export const glbUrl = (generationId: string) =>
  `${API_BASE}/api/v1/generations/${generationId}/artifacts/glb`;
export const isGenerationId = (s: string) => /^[0-9a-f]{32}$/.test(s);
