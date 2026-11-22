import { API_BASE, send } from "./api";

// Client for the project/version endpoints (owner-only; other users' ids give 404).
export type ProjectSummary = { id: string; name: string; floor_count: number; version: number; updated_at: string; thumbnail: string | null };
export type RecentGeneration = {
  generation_id: string;
  created_at: string;
  project_id: string | null;
  project_name: string | null;
  floor_id: string | null;
  floor_name: string | null;
};
export type VersionInfo = { number: number; created_at: string; created_by: string | null; message: string; floor_count: number };

type Fetch = typeof fetch;
const url = (path: string) => `${API_BASE}/api/v1${path}`;
// `send` spreads a JSON object, so lists are wrapped as {items}; 204 becomes {}.
const listOf = <T,>(path: string, f: Fetch) =>
  send<{ items: T[] }>(async () => {
    const res = await f(url(path), { credentials: "include" });
    return res.ok ? new Response(JSON.stringify({ items: await res.json() })) : res;
  });
const call = (method: string, path: string, f: Fetch, body?: unknown) =>
  send<Record<string, unknown>>(async () => {
    const res = await f(url(path), {
      method,
      credentials: "include",
      ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    });
    return res.status === 204 ? new Response("{}") : res;
  });

export const listProjects = (f: Fetch = fetch) => listOf<ProjectSummary>("/projects", f);
export const recentGenerations = (f: Fetch = fetch) => listOf<RecentGeneration>("/generations/recent", f);
export const listVersions = (pid: string, f: Fetch = fetch) => listOf<VersionInfo>(`/projects/${pid}/versions`, f);
export const restoreVersion = (pid: string, n: number, f: Fetch = fetch) => call("POST", `/projects/${pid}/versions/${n}/restore`, f);
export const renameProject = (pid: string, name: string, f: Fetch = fetch) => call("PATCH", `/projects/${pid}`, f, { name });
export const deleteProject = (pid: string, f: Fetch = fetch) => call("DELETE", `/projects/${pid}`, f);

/** "2026-05-01T10:20:30+00:00" -> "2026-05-01 10:20 UTC" (stable across locales and SSR). */
export const shortDate = (iso: string) => `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
