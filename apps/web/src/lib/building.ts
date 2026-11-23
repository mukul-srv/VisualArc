import { API_BASE, send } from "./api";

// Building assembly (GET /projects/{id}/building): floors by elevation, per-floor plan offsets,
// stair pairings and building-wide issues. The viewer consumes the same shape.
type Fetch = typeof fetch;
export type PairStatus = "auto" | "confirmed" | "rejected";
export type PairRef = { lower_floor: string; lower_stair: string; upper_floor: string; upper_stair: string };
export type Pairing = PairRef & { status: PairStatus; overlap: number };
export type BuildingFloor = {
  id: string;
  name: string;
  generation_id: string;
  elevation: number;
  finished_level: number;
  top: number;
  offset: { x: number; y: number; unit: "mm"; source: "user_provided" | "defaulted" };
  bbox: [number, number, number, number] | null; // plan bbox with the offset applied
  area_mm2: number;
  room_count: number;
  stairs: { id: string; polygon: [number, number][]; total_rise: number | null }[];
};
export type BuildingIssue = { code: string; severity: "warning" | "info"; message: string; floor_ids: string[] };
export type Building = {
  project_id: string;
  version: number;
  floors: BuildingFloor[];
  pairings: Pairing[];
  issues: BuildingIssue[];
  stats: { floor_count: number; room_count: number; total_area_mm2: number; stair_count: number; height_mm: number };
};

const url = (path: string) => `${API_BASE}/api/v1/projects/${path}`;
const json = (method: string, body: unknown): RequestInit => ({
  method,
  credentials: "include",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getBuilding = (pid: string, f: Fetch = fetch, share?: string | null) =>
  send<{ building: Building }>(async () => {
    const res = await f(url(`${pid}/building${share ? `?share=${encodeURIComponent(share)}` : ""}`), { credentials: "include" });
    return res.ok ? new Response(JSON.stringify({ building: await res.json() })) : res;
  });
export const setOffset = (pid: string, floorId: string, x: number, y: number, f: Fetch = fetch) =>
  send<Record<string, unknown>>(() => f(url(`${pid}/floors/${floorId}/offset`), json("PUT", { x, y })));
/** Confirm a pair; also the way to re-pair (it replaces any pair using either stair). */
export const confirmPairing = (pid: string, p: PairRef, f: Fetch = fetch) =>
  send<Record<string, unknown>>(() => f(url(`${pid}/building/pairings`), json("PUT", p)));
export const unpair = (pid: string, p: PairRef, f: Fetch = fetch) =>
  send<Record<string, unknown>>(() => f(url(`${pid}/building/pairings/unpair`), json("POST", p)));

export type PairRow = { key: string; ref: PairRef; label: string; status: PairStatus; overlapPct: number };

/** One readable row per pairing, lowest floor first, with floor names resolved. */
export function pairRows(b: Building): PairRow[] {
  const name = (id: string) => b.floors.find((f) => f.id === id)?.name ?? id;
  const order = (id: string) => b.floors.findIndex((f) => f.id === id);
  return b.pairings
    .map((p) => ({
      key: `${p.lower_floor}/${p.lower_stair}>${p.upper_floor}/${p.upper_stair}`,
      ref: { lower_floor: p.lower_floor, lower_stair: p.lower_stair, upper_floor: p.upper_floor, upper_stair: p.upper_stair },
      label: `${name(p.lower_floor)} ${p.lower_stair} to ${name(p.upper_floor)} ${p.upper_stair}`,
      status: p.status,
      overlapPct: Math.round(p.overlap * 100),
    }))
    .sort((a, c) => order(a.ref.lower_floor) - order(c.ref.lower_floor) || a.label.localeCompare(c.label));
}

/** Stairs on a floor with no pairing upward (rejected counts as unpaired): candidates to re-pair. */
export function unpairedStairs(b: Building, floorId: string): string[] {
  const f = b.floors.find((x) => x.id === floorId);
  const paired = new Set(b.pairings.filter((p) => p.status !== "rejected" && p.lower_floor === floorId).map((p) => p.lower_stair));
  return f ? f.stairs.map((s) => s.id).filter((s) => !paired.has(s)) : [];
}

/** True when two building payloads are equal (a refresh that changed nothing must not re-place the floors). */
export const sameBuilding = (a: Building | null, b: Building) => a !== null && JSON.stringify(a) === JSON.stringify(b);
