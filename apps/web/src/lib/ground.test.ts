import { expect, test } from "vitest";
import * as THREE from "three";
import { collectSupports, dampTo, fall, groundLevel, maxRiser, stepOnto, stepUpLimit } from "./ground";

/** The ground at a point, or null when the move is blocked (the tests below judge both). */
const resolveHeight = (x: number, z: number, feet: number, travel: number, supports: THREE.Mesh[], base: number, stepUp: number) => {
  const r = stepOnto(x, z, feet, travel, supports, base, stepUp);
  return r.ok ? r.ground : null;
};

const box = (type: string, x0: number, x1: number, y0: number, y1: number, z0 = 0, z1 = 1, extra: object = {}) => {
  const m = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0), new THREE.MeshBasicMaterial());
  m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
  m.userData = { type, ...extra };
  m.updateMatrixWorld(true);
  return m;
};

// 19 treads of 0.25 m, risers of 0.16 m, like fixture_stairs: block k spans x in [(k-1)*.25, k*.25], top k*.16
function stairModel() {
  const g = new THREE.Group();
  for (let k = 1; k <= 19; k++) g.add(box("stair", (k - 1) * 0.25, k * 0.25, 0, k * 0.16, 0, 1, k === 1 ? { riser_height: { value: 160 } } : {}));
  g.add(box("floor_boundary", -3, 0, -0.001, 0, 0, 1)); // the floor in front of the stair
  g.updateMatrixWorld(true);
  return g;
}

/** Walk along +x in `d` m increments; the new height is applied each step, a null result stops. */
function walkX(model: THREE.Object3D, x: number, feet: number, to: number, d = 0.05) {
  const supports = collectSupports(model);
  const limit = stepUpLimit(model);
  for (; x < to - 1e-9; ) {
    const nx = Math.min(to, x + d);
    const y = resolveHeight(nx, 0.5, feet, nx - x, supports, 0, limit);
    if (y === null) return { x, feet, blocked: true };
    x = nx;
    feet = y;
  }
  return { x, feet, blocked: false };
}

test("the step limit comes from the stairs' own riser", () => {
  const m = stairModel();
  expect(maxRiser(m)).toBeCloseTo(0.16);
  expect(stepUpLimit(m)).toBeCloseTo(0.18);
  expect(stepUpLimit(new THREE.Group())).toBeCloseTo(0.22); // no stairs: the kerb-sized default
});

test("walking along a stair climbs one riser per tread to the top tread", () => {
  const r = walkX(stairModel(), -1, 0, 19 * 0.25 - 0.01);
  expect(r.blocked).toBe(false);
  expect(r.feet).toBeCloseTo(19 * 0.16); // 19 treads: the top riser meets the floor above
});

test("a wall of two risers cannot be stepped onto, and stepping back down is allowed", () => {
  const g = new THREE.Group();
  g.add(box("stair", 0, 1, 0, 0.16, 0, 1, { riser_height: { value: 160 } }), box("stair", 1, 2, 0, 0.5, 0, 1)); // 0.34 above the first step
  g.updateMatrixWorld(true);
  const up = walkX(g, -0.5, 0, 3);
  expect(up).toMatchObject({ blocked: true });
  expect(up.feet).toBeCloseTo(0.16); // got onto the first step, not the second
  const supports = collectSupports(g);
  expect(resolveHeight(0.5, 0.5, 0.5, 0.05, supports, 0, 0.18)).toBeCloseTo(0.16); // down a riser
});

test("a ramp is climbed within the slope limit and refused when steeper", () => {
  const ramp = (rise: number) => {
    const g = new THREE.Group();
    const m = box("ramp", 0, 4, -0.2, 0, 0, 1);
    // shear the slab so its top rises from 0 at x=0 to `rise` at x=4 (like the engine's ramp)
    const a = m.geometry.attributes.position;
    for (let i = 0; i < a.count; i++) a.setY(i, a.getY(i) + (rise * (a.getX(i) + 2)) / 4);
    m.updateMatrixWorld(true);
    g.add(m);
    g.updateMatrixWorld(true);
    return g;
  };
  const gentle = walkX(ramp(2), 0.1, 0.05, 3.9, 0.05); // slope 0.5
  expect(gentle.blocked).toBe(false);
  expect(gentle.feet).toBeCloseTo((2 * 3.9) / 4, 1);
  const steep = walkX(ramp(8), 0.1, 0.2, 3.9, 0.05); // slope 2 > 1
  expect(steep.blocked).toBe(true);
});

test("off the side of a raised surface the walker drops to the baseline", () => {
  const g = new THREE.Group();
  g.add(box("stair", 0, 1, 0, 0.16, 0, 1, { riser_height: { value: 160 } }));
  g.updateMatrixWorld(true);
  expect(resolveHeight(5, 0.5, 0.16, 0.05, collectSupports(g), 0, 0.18)).toBe(0); // no support there
});

test("the ground level is the common base of slab and walls", () => {
  const g = new THREE.Group();
  // slab 0..0.2 inside walls 0..3.2: both start at the base (y = 0), the finished floor is 0.2
  g.add(box("slab", 0.2, 4.8, 0, 0.2, 0.2, 4.8), box("wall", 0, 5, 0, 3.2, 0, 0.2), box("wall", 0, 5, 0, 3.2, 4.8, 5));
  g.updateMatrixWorld(true);
  expect(groundLevel(g)).toBeCloseTo(0); // the grid: where the walls (and the slab) start
  expect(groundLevel(g, 3200)).toBeCloseTo(3.2); // a project's lowest floor base wins when known
  expect(groundLevel(new THREE.Group())).toBe(0);
});

test("the eye height eases to the target without overshoot, whatever the frame rate", () => {
  const run = (fps: number, seconds: number) => {
    let y = 1.6;
    for (let i = 0; i < Math.round(fps * seconds); i++) y = dampTo(y, 1.76, 1 / fps); // one tread (0.16 m) up
    return y;
  };
  expect(run(60, 0.5)).toBeCloseTo(run(30, 0.5), 9); // frame-rate independent (whole frames)
  expect(run(144, 0.5)).toBeCloseTo(run(24, 0.5), 9);
  let y = 1.6;
  let prev = y;
  for (let i = 0; i < 120; i++) {
    y = dampTo(y, 1.76, 1 / 60);
    expect(y).toBeGreaterThanOrEqual(prev); // monotonic: no jitter
    expect(y).toBeLessThanOrEqual(1.76 + 1e-12); // no overshoot
    prev = y;
  }
  expect(y).toBeCloseTo(1.76, 3); // settles
  expect(dampTo(1.6, 1.76, 0)).toBe(1.6); // no time, no move
  expect(dampTo(1.76, 1.6, 1 / 60)).toBeLessThan(1.76); // easing down works too (stepping off, falling)
});

test("climbing tread by tread, the eased eye never jumps more than a small step per frame", () => {
  const supports = collectSupports(stairModel());
  const model = stairModel();
  const limit = stepUpLimit(model);
  let x = -1, feet = 0, eye = 1.6;
  let maxJump = 0;
  while (x < 4.7) {
    const nx = x + 0.033; // 2 m/s at 60 fps
    const y = resolveHeight(nx, 0.5, feet, 0.033, supports, 0, limit);
    if (y === null) break;
    x = nx;
    feet = y;
    const next = dampTo(eye, feet + 1.6, 1 / 60);
    maxJump = Math.max(maxJump, Math.abs(next - eye));
    eye = next;
  }
  expect(feet).toBeGreaterThan(2.5);
  expect(maxJump).toBeLessThan(0.16 * 0.3); // under a third of a riser per frame (unsmoothed it is the whole riser); the ground stays exact
});

test("a stair is a solid mass: from the floor its side, its riser and the space under a ramp are blocked", () => {
  const g = new THREE.Group();
  // a flight of 19 treads (x 0..4.75, z 0..1) and a ramp wedge beside it (z 2..3) rising to 3 m at x = 4
  for (let k = 1; k <= 19; k++) g.add(box("stair", (k - 1) * 0.25, k * 0.25, 0, k * 0.16, 0, 1, k === 1 ? { riser_height: { value: 160 } } : {}));
  const ramp = box("ramp", 0, 4, -0.2, 0, 2, 3);
  const a = ramp.geometry.attributes.position;
  for (let i = 0; i < a.count; i++) a.setY(i, a.getY(i) + (3 * (a.getX(i) + 2)) / 4);
  ramp.updateMatrixWorld(true);
  g.add(ramp, box("floor_boundary", -5, 8, -0.001, 0, -3, 6));
  g.updateMatrixWorld(true);
  const supports = collectSupports(g);
  const limit = stepUpLimit(g);
  const moveIn = (from: [number, number], to: [number, number], feet = 0) => resolveHeight(to[0], to[1], feet, Math.hypot(to[0] - from[0], to[1] - from[1]), supports, 0, limit);
  expect(moveIn([2.0, -0.1], [2.0, 0.05])).toBeNull(); // the side of tread 8 (top 1.28 m)
  expect(moveIn([4.0, -0.1], [4.0, 0.05])).toBeNull(); // the side, further up
  expect(moveIn([-0.1, 0.5], [0.2, 0.5], 0)).toBeCloseTo(0.16); // the front: onto the first tread
  expect(moveIn([0.2, 0.5], [0.3, 0.5], 0)).toBeNull(); // the second riser from the floor: too high a step
  expect(moveIn([2.0, 3.1], [2.0, 2.9])).toBeNull(); // the side of the ramp (2 m up there)
  expect(moveIn([3.0, 1.9], [3.0, 2.1])).toBeNull(); // under the ramp: the floor is there, the ramp is not passable from below
});

test("walking off the side of a stair or ramp is allowed; the walker FALLS to the floor, eased, without teleporting", () => {
  const g = new THREE.Group();
  for (let k = 1; k <= 19; k++) g.add(box("stair", (k - 1) * 0.25, k * 0.25, 0, k * 0.16, 0, 1, k === 1 ? { riser_height: { value: 160 } } : {}));
  g.add(box("floor_boundary", -5, 8, -0.001, 0, -3, 6));
  g.updateMatrixWorld(true);
  const supports = collectSupports(g);
  const limit = stepUpLimit(g);
  // standing on tread 12 (top 1.92 m), stepping sideways off the stair at z = 1.05
  const r = stepOnto(2.9, 1.05, 1.92, 0.05, supports, 0, limit);
  expect(r).toEqual({ ok: true, ground: expect.closeTo(0, 6) }); // allowed; the ground is the floor, 1.92 m below
  let feet = 1.92, vy = 0, prev = feet, maxStep = 0, frames = 0;
  while (feet > 0 && frames < 600) {
    ({ feet, vy } = fall(feet, 0, vy, 1 / 60));
    expect(feet).toBeLessThanOrEqual(prev); // monotonic
    maxStep = Math.max(maxStep, prev - feet);
    prev = feet;
    frames++;
  }
  expect(feet).toBe(0); // landed
  expect(vy).toBe(0);
  expect(frames).toBeGreaterThan(20); // not a teleport: about 0.6 s of falling
  expect(maxStep).toBeLessThan(0.4); // fastest frame: well under half a metre
  // a step up is taken at once, and a walker already on the ground stays
  expect(fall(0, 0.16, 0, 1 / 60)).toEqual({ feet: 0.16, vy: 0 });
  expect(fall(0.5, 0.5, 0, 1 / 60)).toEqual({ feet: 0.5, vy: 0 });
});

test("no tunnelling: a falling walker beside the stair still cannot enter its body", () => {
  const g = new THREE.Group();
  for (let k = 1; k <= 19; k++) g.add(box("stair", (k - 1) * 0.25, k * 0.25, 0, k * 0.16, 0, 1, k === 1 ? { riser_height: { value: 160 } } : {}));
  g.add(box("floor_boundary", -5, 8, -0.001, 0, -3, 6));
  g.updateMatrixWorld(true);
  const supports = collectSupports(g);
  // at 0.7 m above the floor (mid-fall) walking back into tread 12's side (top 1.92): blocked
  expect(resolveHeight(2.9, 0.95, 0.7, 0.05, supports, 0, 0.18)).toBeNull();
});
