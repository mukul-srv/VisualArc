import { expect, test } from "vitest";
import type { Building } from "./building";
import { blockedHint, blockedStairAt, blockedStairs, buildingStats, floorAtHeight, floorState, floorStats, GAP, manifestBuilding, placements, walkableFloors, type View } from "./building-view";

const st = (id: string, x0 = 0): { id: string; polygon: [number, number][]; total_rise: number } => ({
  id, total_rise: 3200, polygon: [[x0, 0], [x0 + 1000, 0], [x0 + 1000, 2000], [x0, 2000]],
});
const fl = (id: string, name: string, elevation: number, stairs: ReturnType<typeof st>[], ox = 0, oy = 0) => ({
  id, name, generation_id: "g", elevation, finished_level: elevation + 200, top: elevation + 3200,
  offset: { x: ox, y: oy, unit: "mm" as const, source: "defaulted" as const }, bbox: null, area_mm2: 50e6, room_count: 4, stairs,
});
const pair = (lf: string, ls: string, uf: string, us: string, status = "auto") => ({ lower_floor: lf, lower_stair: ls, upper_floor: uf, upper_stair: us, status, overlap: 1 });
const b = {
  project_id: "p", version: 1,
  floors: [fl("f0", "Ground", 0, [st("s1"), st("lost", 5000)]), fl("f1", "First", 3200, [st("t1")], 500, -250), fl("f2", "Second", 6400, [st("u1")])],
  pairings: [pair("f0", "s1", "f1", "t1")],
  issues: [], stats: { floor_count: 3, room_count: 12, total_area_mm2: 150e6, stair_count: 4, height_mm: 9600 },
} as unknown as Building;
const view = (o: Partial<View> = {}): View => ({ mode: "whole", activeId: "f0", gap: GAP.default, ghost: false, ...o });

test("placement applies the plan offset (y flips to -z) and lifts only when exploded", () => {
  expect(placements(b, view()).get("f1")).toEqual({ x: 0.5, y: 0, z: 0.25 });
  const e = placements(b, view({ mode: "exploded", gap: 2 }));
  expect([e.get("f0")!.y, e.get("f1")!.y, e.get("f2")!.y]).toEqual([0, 2, 4]);
  expect(e.get("f1")).toMatchObject({ x: 0.5, z: 0.25 });
});

test("isolate shows the active floor; the others are hidden or ghosted", () => {
  expect(floorState(view(), "f1")).toBe("visible");
  expect(floorState(view({ mode: "isolate" }), "f0")).toBe("visible");
  expect(floorState(view({ mode: "isolate" }), "f1")).toBe("hidden");
  expect(floorState(view({ mode: "isolate", ghost: true }), "f1")).toBe("ghost");
});

test("walking reaches floors joined by pairings; none when unpaired, exploded or hidden", () => {
  expect([...walkableFloors(b, view())].sort()).toEqual(["f0", "f1"]); // f2 has no pairing
  expect([...walkableFloors(b, view({ activeId: "f1" }))].sort()).toEqual(["f0", "f1"]); // also downwards
  expect(walkableFloors(b, view({ mode: "exploded" })).size).toBe(0);
  expect([...walkableFloors(b, view({ mode: "isolate" }))]).toEqual(["f0"]);
  expect([...walkableFloors(b, view({ mode: "isolate", ghost: true }))]).toEqual(["f0"]);
  const rejected = { ...b, pairings: [pair("f0", "s1", "f1", "t1", "rejected")] } as Building;
  expect([...walkableFloors(rejected, view())]).toEqual(["f0"]);
  const chain = { ...b, pairings: [...b.pairings, pair("f1", "t1", "f2", "u1", "confirmed")] } as Building;
  expect([...walkableFloors(chain, view())].sort()).toEqual(["f0", "f1", "f2"]);
});

test("unpaired stairs under a floor are blocked, with a hint; top-floor stairs are not", () => {
  expect([...blockedStairs(b)]).toEqual(["f0/lost"]); // s1 and t1 are paired, u1 is on the top floor
  const h = blockedStairAt(b, "f0", 5.5, -1);
  expect(h).toEqual({ stair: "lost", floor: "Ground", above: "First" });
  expect(blockedHint(h!)).toContain("not paired");
  expect(blockedStairAt(b, "f0", 0.5, -1)).toBeNull(); // s1 is paired
  expect(blockedStairAt(b, "f0", 20, 20)).toBeNull();
});

test("the walker's floor follows their height, including the exploded lift", () => {
  expect(floorAtHeight(b, view(), 0.2)).toBe("f0");
  expect(floorAtHeight(b, view(), 3.3)).toBe("f1"); // top of the flight
  expect(floorAtHeight(b, view(), 3.0)).toBe("f0");
  expect(floorAtHeight(b, view({ mode: "exploded", gap: 2 }), 5.2)).toBe("f1");
});

test("stats and the history-view fallback", () => {
  expect(buildingStats(b)).toEqual({ floors: 3, rooms: 12, area: "150.0 m²", height: "9.60 m" });
  expect(floorStats(b.floors[1])).toEqual({ rooms: 4, area: "50.0 m²", height: "3.20 m" });
  const m = manifestBuilding({ id: "p", name: "P", floors: [
    { id: "b", name: "B", elevation: { value: 3000, unit: "mm", source: "user_provided" }, generation_id: "x", offset: { x: 5, y: 6, unit: "mm", source: "user_provided" } },
    { id: "a", name: "A", elevation: { value: 0, unit: "mm", source: "user_provided" }, generation_id: "y" },
  ] } as never);
  expect(m.floors.map((f) => f.id)).toEqual(["a", "b"]);
  expect(placements(m, view()).get("b")).toEqual({ x: 0.005, y: 0, z: -0.006 });
  expect(blockedStairs(m).size).toBe(0);
});
