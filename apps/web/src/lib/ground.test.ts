import { expect, test } from "vitest";
import * as THREE from "three";
import { collectSupports, groundLevel, maxRiser, resolveHeight, stepUpLimit } from "./ground";

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

test("the ground level is the floor level, not the slab underside", () => {
  const g = new THREE.Group();
  g.add(box("slab", 0, 5, -0.2, 0, 0, 5), box("wall", 0, 5, 0, 3, 0, 0.2), box("wall", 0, 5, 0, 3, 4.8, 5));
  g.updateMatrixWorld(true);
  expect(groundLevel(g)).toBeCloseTo(0); // walls start at the floor, the slab is below grade
  expect(groundLevel(g, 3200)).toBeCloseTo(3.2); // a project's lowest floor wins when known
  expect(groundLevel(new THREE.Group())).toBe(0);
});
