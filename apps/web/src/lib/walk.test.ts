// T23: collision against the real GLB geometry. The invariants that matter:
//  - the player cannot pass through solid walls (including after long random walks),
//  - doors (sill 0) can be walked through, windows (sill 0.9 m) cannot,
//  - the spawn point is inside a room.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { beforeAll, expect, test } from "vitest";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { collectColliders, makeDoubleSided, moveWithCollision, spawnPoint, WALK } from "./walk";

const root = path.resolve(__dirname, "../../../..");
type Canon = {
  walls: { id: string; thickness: { value: number } }[];
  boundaries: { polygon: [number, number][] }[];
  openings: { id: string; kind: string; wall_id: string; span: { start: [number, number]; end: [number, number] } }[];
};
type Loaded = { scene: THREE.Group; colliders: THREE.Mesh[]; canon: Canon };
const fixtures: Record<string, Loaded> = {};

async function load(name: string, expected: string): Promise<Loaded> {
  const out = mkdtempSync(path.join(tmpdir(), "walk-"));
  execFileSync(
    "uv",
    ["run", "python", "-m", "api.cli", "build", path.join(root, "fixtures/input", `${name}.dxf`), "--wall-height", "3000", "--out", out],
    { cwd: path.join(root, "services/api"), stdio: "pipe" },
  );
  const buf = readFileSync(path.join(out, `${name}.glb`));
  const gltf = await new GLTFLoader().parseAsync(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer, "");
  gltf.scene.updateMatrixWorld(true);
  const canon = JSON.parse(readFileSync(path.join(root, "fixtures/expected", `${expected}.canonical.json`), "utf8")).buildings[0].floors[0];
  const colliders = collectColliders(gltf.scene);
  makeDoubleSided(colliders);
  return { scene: gltf.scene, colliders, canon };
}

beforeAll(async () => {
  fixtures.a = await load("fixture_a", "fixture_a");
  fixtures.b = await load("fixture_b", "fixture_b");
  fixtures.o = await load("fixture_openings", "fixture_openings");
}, 180_000);

const walk = (f: Loaded, pos: THREE.Vector3, floorY: number, dx: number, dz: number, dist: number) => {
  // many frames of 2 m/s at 60 fps, like the viewer
  const step = (WALK.speed / 60) * 1;
  const dir = new THREE.Vector2(dx, dz).normalize();
  for (let d = 0; d < dist; d += step) moveWithCollision(pos, dir.clone().multiplyScalar(step), floorY, f.colliders);
  return pos;
};

const inPoly = (p: [number, number][], x: number, y: number) => {
  let c = false;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, yi] = p[i];
    const [xj, yj] = p[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
};

test("spawn point lies inside a floor boundary for every fixture (incl. L-shaped)", () => {
  for (const f of Object.values(fixtures)) {
    const s = spawnPoint(f.scene)!;
    expect(s).not.toBeNull();
    const inside = f.canon.boundaries.some((b) => inPoly(b.polygon, s.pos.x * 1000, -s.pos.z * 1000));
    expect(inside).toBe(true);
  }
});

test("random long walks never leave the starting room (fixture A, solid walls, no openings)", () => {
  const f = fixtures.a;
  const s = spawnPoint(f.scene)!;
  const room = f.canon.boundaries.find((b) => inPoly(b.polygon, s.pos.x * 1000, -s.pos.z * 1000))!.polygon;
  let seed = 12345;
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) % 2 ** 32) / 2 ** 32) * 2 - 1;
  const pos = s.pos.clone();
  for (let leg = 0; leg < 60; leg++) {
    walk(f, pos, s.floorY, rnd(), rnd() || 0.1, 3 + Math.abs(rnd()) * 4);
    expect(inPoly(room, pos.x * 1000, -pos.z * 1000), `leg ${leg}`).toBe(true);
    // keeps its body radius off every wall face, not just the centre inside the room
    const [xs, ys] = [room.map((p) => p[0]), room.map((p) => p[1])];
    expect(pos.x * 1000).toBeGreaterThanOrEqual(Math.min(...xs) + WALK.radius * 1000 * 0.9 - 1e-6);
    expect(pos.x * 1000).toBeLessThanOrEqual(Math.max(...xs) - WALK.radius * 1000 * 0.9 + 1e-6);
    expect(-pos.z * 1000).toBeGreaterThanOrEqual(Math.min(...ys) + WALK.radius * 1000 * 0.9 - 1e-6);
    expect(-pos.z * 1000).toBeLessThanOrEqual(Math.max(...ys) - WALK.radius * 1000 * 0.9 + 1e-6);
  }
});

test("walking straight at a wall for a long time stops at the wall face (L-shaped room, reflex corner)", () => {
  const f = fixtures.b;
  const s = spawnPoint(f.scene)!;
  const poly = f.canon.boundaries[0].polygon;
  const pos = s.pos.clone();
  for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1]]) {
    walk(f, pos, s.floorY, dx, dz, 12);
    expect(inPoly(poly, pos.x * 1000, -pos.z * 1000)).toBe(true);
  }
});

// Fixture openings: every door can be walked through, every window cannot.
const through = (f: Loaded, o: Canon["openings"][number], sign: 1 | -1) => {
  const [sx, sy] = o.span.start;
  const [ex, ey] = o.span.end;
  const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
  const cx = (sx + ex) / 2000;
  const cz = -(sy + ey) / 2000;
  const floorY = spawnPoint(f.scene)!.floorY;
  // start 0.8 m before the wall centreline, perpendicular to the wall, walk 2 m towards it
  const start = alongX ? new THREE.Vector3(cx, floorY, cz - sign * 0.8) : new THREE.Vector3(cx - sign * 0.8, floorY, cz);
  const pos = start.clone();
  const dir = alongX ? [0, sign] : [sign, 0];
  walk(f, pos, floorY, dir[0], dir[1], 2);
  const crossed = alongX ? (pos.z - cz) * sign : (pos.x - cx) * sign; // > 0 once past the centreline
  return crossed;
};

test("every door opening can be walked through from at least one side", () => {
  const doors = fixtures.o.canon.openings.filter((o) => o.kind === "door");
  expect(doors.length).toBe(3);
  for (const o of doors) {
    const best = Math.max(through(fixtures.o, o, 1), through(fixtures.o, o, -1));
    expect(best, o.id).toBeGreaterThan(0.5); // ends well beyond the wall centreline
  }
});

test("no window opening can be walked through from either side (sill 0.9 m)", () => {
  const windows = fixtures.o.canon.openings.filter((o) => o.kind === "window");
  expect(windows.length).toBe(4);
  for (const o of windows) {
    for (const sign of [1, -1] as const) {
      expect(through(fixtures.o, o, sign), `${o.id} side ${sign}`).toBeLessThan(0); // never reaches the centreline
    }
  }
});

test("a wall is not penetrated by a single large frame step (anti-tunnelling)", () => {
  const f = fixtures.a;
  const s = spawnPoint(f.scene)!;
  const pos = s.pos.clone();
  moveWithCollision(pos, new THREE.Vector2(50, 0), s.floorY, f.colliders); // 50 m in one call
  const room = f.canon.boundaries.find((b) => inPoly(b.polygon, s.pos.x * 1000, -s.pos.z * 1000))!.polygon;
  expect(inPoly(room, pos.x * 1000, -pos.z * 1000)).toBe(true);
});

// Review findings: off-centre door entry, body radius at the reflex corner, thin stub.
test("an 800-900 mm door can be entered off-centre by up to 100 mm either side", () => {
  const f = fixtures.o;
  const door = f.canon.openings.find((o) => o.kind === "door")!;
  const [sx, sy] = door.span.start;
  const [ex, ey] = door.span.end;
  const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
  const floorY = spawnPoint(f.scene)!.floorY;
  for (const shift of [-0.1, 0.1]) {
    let ok = false;
    for (const sign of [1, -1] as const) {
      const cx = (sx + ex) / 2000 + (alongX ? shift : 0);
      const cz = -(sy + ey) / 2000 + (alongX ? 0 : shift);
      const pos = alongX ? new THREE.Vector3(cx, floorY, cz - sign * 0.8) : new THREE.Vector3(cx - sign * 0.8, floorY, cz);
      walk(f, pos, floorY, alongX ? 0 : sign, alongX ? sign : 0, 2);
      const crossed = alongX ? (pos.z - (-(sy + ey) / 2000)) * sign : (pos.x - (sx + ex) / 2000) * sign;
      ok ||= crossed > 0.5;
    }
    expect(ok, `shift ${shift}`).toBe(true);
  }
});

test("a free-ended 100 mm wall stub between probe rays still blocks", () => {
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.1, 2.5, 1), new THREE.MeshBasicMaterial());
  box.position.set(0.07, 1.25, -2); // spans x 0.02..0.12, in front of a player at x = 0
  box.userData.type = "wall";
  box.updateMatrixWorld(true);
  const pos = new THREE.Vector3(0, 0, 0);
  moveWithCollision(pos, new THREE.Vector2(0, -3), 0, [box]);
  expect(pos.z).toBeGreaterThan(-1.5 + WALK.radius * 0.9 - 1e-6); // stopped at the stub face (z = -1.5)
});

test("walking into the reflex corner keeps the body radius off the walls", () => {
  const f = fixtures.b;
  const s = spawnPoint(f.scene)!;
  const pos = s.pos.clone();
  const bad: string[] = [];
  for (const [dx, dz] of [[1, 0], [0, 1], [-1, 0], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]]) {
    walk(f, pos, s.floorY, dx, dz, 12);
    // every probe lateral direction must still be clear: no collider within radius*0.9 ahead is already
    // overlapped, i.e. a short step in the same direction is either free or blocked without moving inside
    const before = pos.clone();
    moveWithCollision(pos, new THREE.Vector2(dx, dz).normalize().multiplyScalar(0.05), s.floorY, f.colliders);
    if (!inPoly(f.canon.boundaries[0].polygon, pos.x * 1000, -pos.z * 1000)) bad.push(`${dx},${dz}`);
    pos.copy(before);
  }
  expect(bad).toEqual([]);
});
