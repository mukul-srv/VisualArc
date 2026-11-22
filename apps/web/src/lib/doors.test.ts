import { expect, test } from "vitest";
import * as THREE from "three";
import { animate, blocking, buildDoors, canClose, DOOR, doorFor, hingeOf, nearestDoor, toggle, whyNoToggle } from "./doors";
import type { OpeningData } from "./selection";

const m = (value: number) => ({ value, unit: "mm", source: "defaulted" as const });
const door = (over: Partial<OpeningData> = {}): OpeningData =>
  ({
    id: "opening-003", kind: "door", wall_id: "wall-001",
    span: { start: [7500, 100], end: [8400, 100] }, // fixture_openings D3: along x, wall centre y = 100
    offset: m(0), width: m(900), height: m(2100), sill_height: m(0), sources: [],
    swing: { hinge: "start", opens_toward: "+y", source: { layer: "A-DOOR", entity_handle: "39" } },
    detail: { frame_width: m(50), panel: "leaf", panel_thickness: m(40) },
    ...over,
  }) as OpeningData;

/** The leaf's free-edge direction after the quarter turn, in plan (x, y). */
function swungTo(o: OpeningData) {
  const h = hingeOf(o)!;
  const alongX = Math.abs(o.span.end[0] - o.span.start[0]) >= Math.abs(o.span.end[1] - o.span.start[1]);
  const s = o.swing!.hinge === "start" ? 1 : -1;
  const v = alongX ? new THREE.Vector3(s, 0, 0) : new THREE.Vector3(0, 0, -s); // plan (0, s) -> three z = -s
  v.applyAxisAngle(new THREE.Vector3(0, 1, 0), h.angle);
  return [Math.round(v.x) + 0, Math.round(-v.z) + 0]; // + 0: no -0
}

test.each([
  ["start", "+y", 7500, [0, 1]], ["start", "-y", 7500, [0, -1]],
  ["end", "+y", 8400, [0, 1]], ["end", "-y", 8400, [0, -1]],
])("a door along x hinged at its %s opening toward %s swings its leaf that way", (hinge, toward, _x, want) => {
  const o = door({ swing: { hinge, opens_toward: toward, source: { layer: "A-DOOR", entity_handle: "1" } } as OpeningData["swing"] });
  expect(swungTo(o)).toEqual(want);
});

test.each([
  ["start", "+x", [1, 0]], ["start", "-x", [-1, 0]], ["end", "+x", [1, 0]], ["end", "-x", [-1, 0]],
])("a door along y hinged at its %s opening toward %s swings its leaf that way", (hinge, toward, want) => {
  const o = door({
    span: { start: [3250, 1000], end: [3250, 1900] },
    swing: { hinge, opens_toward: toward, source: { layer: "A-DOOR", entity_handle: "1" } } as OpeningData["swing"],
  });
  expect(swungTo(o)).toEqual(want);
});

test("the pivot sits on the wall centreline, inside the frame, at the hinge end", () => {
  const a = hingeOf(door())!;
  expect(a.pivot.x).toBeCloseTo(7.55); // 7500 + 50 mm frame
  expect(a.pivot.z).toBeCloseTo(-0.1); // plan y 100 mm -> three z = -0.1
  const b = hingeOf(door({ swing: { hinge: "end", opens_toward: "+y", source: { layer: "A-DOOR", entity_handle: "1" } } }))!;
  expect(b.pivot.x).toBeCloseTo(8.35);
});

test("no swing or a window gives no hinge", () => {
  expect(hingeOf(door({ swing: null }))).toBeNull();
  expect(hingeOf(door({ kind: "window" }))).toBeNull();
});

function modelWithLeaf(o = door()) {
  const g = new THREE.Group();
  // the leaf as the engine builds it: x 7550..8350, wall y 80..120 (three z -0.12..-0.08), z (up) 0..2.05
  const leaf = new THREE.Mesh(new THREE.BoxGeometry(0.8, 2.05, 0.04), new THREE.MeshBasicMaterial());
  leaf.position.set(7.95, 1.025, -0.1);
  leaf.userData = { type: "opening_part", part: "leaf", opening: o };
  g.add(leaf);
  g.updateMatrixWorld(true);
  return { g, leaf };
}

test("toggling swings the leaf about the hinge, and back, with the door passable while open", () => {
  const { g, leaf } = modelWithLeaf();
  const doors = buildDoors(g);
  expect(doors).toHaveLength(1);
  const closed = new THREE.Box3().setFromObject(leaf);
  expect(closed.min.x).toBeCloseTo(7.55);
  expect(blocking(doors)).toEqual([leaf]); // closed: solid
  toggle(doors[0]);
  expect(blocking(doors)).toEqual([]); // open (or opening): passable at once
  for (let i = 0; i < 100; i++) animate(doors, 0.02);
  const open = new THREE.Box3().setFromObject(leaf);
  // opens toward +y plan = more negative three z, still hung at x = 7.55
  expect(open.min.x).toBeCloseTo(7.53, 1);
  expect(open.max.x).toBeCloseTo(7.57, 1);
  expect(open.min.z).toBeCloseTo(-0.9, 1);
  expect(doors[0].angle).toBeCloseTo(DOOR.open);
  toggle(doors[0]);
  for (let i = 0; i < 100; i++) animate(doors, 0.02);
  const back = new THREE.Box3().setFromObject(leaf);
  expect(back.min.x).toBeCloseTo(closed.min.x, 3);
  expect(back.max.x).toBeCloseTo(closed.max.x, 3);
  expect(blocking(doors)).toEqual([leaf]);
});

test("a door without swing data is not interactive and the reason is given; windows say so too", () => {
  const { g } = modelWithLeaf(door({ swing: null }));
  const doors = buildDoors(g);
  expect(doors).toHaveLength(0);
  expect(whyNoToggle(door({ swing: null }), doors)).toMatch(/no swing arc/);
  expect(whyNoToggle(door({ kind: "window" }), doors)).toMatch(/Windows do not open/);
  expect(whyNoToggle(null, doors)).toBeNull();
  const ok = buildDoors(modelWithLeaf().g);
  expect(whyNoToggle(door(), ok)).toBeNull();
  expect(doorFor(ok, "opening-003")).toBe(ok[0]);
});

test("reach picks the nearest door, and a walker in the doorway keeps it from closing", () => {
  const doors = buildDoors(modelWithLeaf().g);
  expect(nearestDoor(doors, new THREE.Vector3(7.9, 0, 0.8))).toBe(doors[0]); // 0.9 m from the opening
  expect(nearestDoor(doors, new THREE.Vector3(7.9, 0, 3))).toBeNull(); // too far
  expect(canClose(doors[0], new THREE.Vector3(7.9, 0, -0.1))).toBe(false); // standing in it
  expect(canClose(doors[0], new THREE.Vector3(7.9, 0, 1.2))).toBe(true);
});
