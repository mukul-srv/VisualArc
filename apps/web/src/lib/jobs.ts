import { API_BASE, send, type FloorParams, type GenerationParams, type Issue, type Failure, type Result } from "./api";
import type { Floor } from "./project";

// Generation jobs: start one, poll its status, resolve with the same shape the synchronous
// endpoints return so callers need no special cases.
export type JobStatus = {
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  progress: number;
  error: string | null;
  result: ({ issues?: Issue[] } & Record<string, unknown>) | null;
};
export type JobProgress = { stage: string; progress: number };
type Fetch = typeof fetch;

export const STAGE_LABEL: Record<string, string> = {
  queued: "Queued",
  parsing: "Reading the DXF",
  "building-model": "Building the model",
  exporting: "Exporting the 3D model",
  done: "Done",
};

const POLL_RETRIES = 4;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;
const url = (p: string) => `${API_BASE}/api/v1/jobs${p}`;

async function run<T>(
  start: () => Promise<Response>,
  onProgress: ((p: JobProgress) => void) | undefined,
  f: Fetch,
  intervalMs: number,
  timeoutMs = POLL_TIMEOUT_MS,
): Promise<Result<T>> {
  const started = await send<{ job_id: string }>(start);
  if (!started.ok) return started;
  const deadline = Date.now() + timeoutMs;
  let errors = 0;
  for (;;) {
    let code = 0; // stays 0 when the request never got a response
    const polled = await send<JobStatus>(async () => {
      const res = await f(url(`/${started.job_id}`), { credentials: "include" });
      code = res.status;
      return res;
    });
    if (!polled.ok) {
      // transient poll errors (network blip, 5xx) are retried; 401/404 and the like are final
      if ((code !== 0 && code < 500) || ++errors > POLL_RETRIES) return polled;
    } else {
      errors = 0;
      onProgress?.({ stage: polled.stage, progress: polled.progress });
      if (polled.status === "succeeded") return { ok: true, ...(polled.result as object) } as Result<T>;
      if (polled.status === "failed") {
        const issues = polled.result?.issues ?? [];
        return { ok: false, kind: issues.length ? "blocked" : "error", message: polled.error ?? "job failed", issues } as Failure;
      }
    }
    if (Date.now() > deadline)
      return { ok: false, kind: "error", message: "Timed out waiting for the job. It may still finish; check the project later.", issues: [] };
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

const startPost = (path: string, body: unknown, f: Fetch) => () =>
  f(url(path), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const generateJob = (params: GenerationParams, onProgress?: (p: JobProgress) => void, f: Fetch = fetch, intervalMs = 500) =>
  run<{ generation_id: string; issues: Issue[] }>(startPost("/generations", params, f), onProgress, f, intervalMs);

export const addFloorJob = (projectId: string, params: FloorParams, onProgress?: (p: JobProgress) => void, f: Fetch = fetch, intervalMs = 500) =>
  run<{ floor: Floor; generation_id: string; issues: Issue[] }>(startPost(`/projects/${projectId}/floors`, params, f), onProgress, f, intervalMs);
