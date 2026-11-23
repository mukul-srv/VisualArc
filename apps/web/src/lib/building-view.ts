import type { Building, BuildingFloor } from "./building";
import type { Manifest } from "./project";

// Pure logic of the building viewer: where each floor goes, what shows, and where a walker may pass.
// The floors' GLBs already carry their own elevation (Y); the viewer only adds the floor's manual
// plan offset (mm, from the project manifest) and, when exploded, a lift per floor.
export type ViewMode = "whole" | "isolate" | "exploded";
export type View = { mode: ViewMode; activeId: string | null; gap: number; ghost: boolean };
export const GAP = { min: 0, max: 10, step: 0.5, default: 3 }; // m of lift per floor above the lowest
export type FloorState = "visible" | "ghost" | "hidden";

export function floorState(v: View, id: string): FloorState {
  if (v.mode !== "isolate" || id === v.activeId) return "visible";
  return v.ghost ? "ghost" : "hidden";
}

/** three.js position (m) of each floor's model: plan (x, y) mm -> (x, -y) m, exploded lift by index. */
export function placements(b: Building, v: View): Map<string, { x: number; y: number; z: number }> {
  return new Map(
    b.floors.map((f, i) => [
      f.id,
      { x: f.offset.x / 1000, y: v.mode === "exploded" ? i * v.gap : 0, z: -f.offset.y / 1000 },
    ]),
  );
}

const linked = (b: Building) => b.pairings.filter((p) => p.status !== "rejected");

/** Floors the walker can reach from the active floor: shown at full strength and joined by a chain of
 *  paired stairs. Exploded floors are apart, so there is no walking at all. */
export function walkableFloors(b: Building, v: View): Set<string> {
  if (v.mode === "exploded" || !v.activeId) return new Set();
  const out = new Set([v.activeId]);
  for (let grew = true; grew; ) {
    grew = false;
    for (const p of linked(b)) {
      for (const [from, to] of [[p.lower_floor, p.upper_floor], [p.upper_floor, p.lower_floor]]) {
        if (out.has(from) && !out.has(to) && floorState(v, to) === "visible") {
          out.add(to);
          grew = true;
        }
      }
    }
  }
  return out;
}

/** Stairs nobody may use: on a floor that has one above, and in no pairing. A stair on the top floor
 *  leads nowhere to gate, so it stays walkable. Keys are `floorId/stairId`. */
export function blockedStairs(b: Building): Set<string> {
  const paired = new Set(linked(b).flatMap((p) => [`${p.lower_floor}/${p.lower_stair}`, `${p.upper_floor}/${p.upper_stair}`]));
  const out = new Set<string>();
  b.floors.slice(0, -1).forEach((f) => f.stairs.forEach((s) => paired.has(`${f.id}/${s.id}`) || out.add(`${f.id}/${s.id}`)));
  return out;
}

/** The unpaired stair the walker (world metres, on floor `floorId`) is at or next to, if any. */
export function blockedStairAt(b: Building, floorId: string, x: number, z: number, margin = 0.3): { stair: string; floor: string; above: string } | null {
  const i = b.floors.findIndex((f) => f.id === floorId);
  const blocked = blockedStairs(b);
  for (const s of b.floors[i]?.stairs ?? []) {
    if (!blocked.has(`${floorId}/${s.id}`)) continue;
    const xs = s.polygon.map((p) => p[0] / 1000);
    const zs = s.polygon.map((p) => -p[1] / 1000);
    if (x >= Math.min(...xs) - margin && x <= Math.max(...xs) + margin && z >= Math.min(...zs) - margin && z <= Math.max(...zs) + margin)
      return { stair: s.id, floor: b.floors[i].name, above: b.floors[i + 1].name };
  }
  return null;
}

export const blockedHint = (h: { stair: string; floor: string; above: string }) =>
  `Stair ${h.stair} on ${h.floor} is not paired with a flight on ${h.above}, so it cannot be climbed. Pair it on the project page (Building).`;

/** The floor a walker with feet at `feetY` (m) stands on: the highest one whose finished floor is at
 *  most a stair-top slack above them (so the top of a flight already counts as the upper floor). */
export function floorAtHeight(b: Building, v: View, feetY: number, slack = 0.35): string | null {
  const lift = placements(b, v);
  let id: string | null = null;
  for (const f of b.floors) if (f.finished_level / 1000 + (lift.get(f.id)?.y ?? 0) - slack <= feetY) id = f.id;
  return id ?? b.floors[0]?.id ?? null;
}

export type Stats = { floors?: number; rooms: number; area: string; height: string };
const m2 = (mm2: number) => `${(mm2 / 1e6).toFixed(1)} m²`;
const metres = (mm: number) => `${(mm / 1000).toFixed(2)} m`;
export const buildingStats = (b: Building): Stats => ({
  floors: b.stats.floor_count, rooms: b.stats.room_count, area: m2(b.stats.total_area_mm2), height: metres(b.stats.height_mm),
});
export const floorStats = (f: BuildingFloor): Stats => ({ rooms: f.room_count, area: m2(f.area_mm2), height: metres(f.top - f.elevation) });

/** History views have no building API data: floors keep their stored offsets, nothing is gated. */
export function manifestBuilding(mf: Manifest): Building {
  const floors = [...mf.floors].sort((a, c) => a.elevation.value - c.elevation.value).map((f) => ({
    id: f.id, name: f.name, generation_id: f.generation_id, elevation: f.elevation.value, finished_level: f.elevation.value,
    top: f.elevation.value, offset: f.offset ?? { x: 0, y: 0, unit: "mm" as const, source: "defaulted" as const },
    bbox: null, area_mm2: 0, room_count: 0, stairs: [],
  }));
  return { project_id: mf.id, version: 0, floors, pairings: [], issues: [], stats: { floor_count: floors.length, room_count: 0, total_area_mm2: 0, stair_count: 0, height_mm: 0 } };
}
