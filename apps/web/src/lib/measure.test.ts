// Snapping and measuring against a real fixture GLB; ground truth from the canonical JSON.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { beforeAll, expect, test } from "vitest";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { measure, snapPoint } from "./measure";

const root = path.resolve(__dirname, "../../../..");
const vp = { width: 1000, height: 800 };
let wall: THREE.Mesh;
let wallCanon: { thickness: { value: number }; height: { value: number } };
let verts: THREE.Vector3[];
const camera = new THREE.PerspectiveCamera(50, vp.width / vp.height, 0.1, 500);

beforeAll(async () => {
  const out = mkdtempSync(path.join(tmpdir(), "meas-"));
  execFileSync(
    "uv",
    ["run", "python", "-m", "api.cli", "build", path.join(root, "fixtures/input/fixture_a.dxf"), "--wall-height", "3000", "--ceiling-height", "3000", "--out", out],
    { cwd: path.join(root, "services/api"), stdio: "pipe" },
  );
  const buf = readFileSync(path.join(out, "fixture_a.glb"));
  const gltf = await new GLTFLoader().parseAsync(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer, "");
  const f = JSON.parse(readFileSync(path.join(root, "fixtures/expected/fixture_a.canonical.json"), "utf8")).buildings[0].floors[0];
  wallCanon = f.walls[0];
  wall = gltf.scene.getObjectByName(f.walls[0].id) as THREE.Mesh;
  wall.updateWorldMatrix(true, false);
  const pos = wall.geometry.getAttribute("position");
  verts = Array.from({ length: pos.count }, (_, i) => new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(wall.matrixWorld));
  const c = new THREE.Box3().setFromObject(wall).getCenter(new THREE.Vector3());
  camera.position.set(c.x + 3, c.y + 3, c.z + 6);
  camera.lookAt(c);
  camera.updateMatrixWorld();
  camera.updateProjectionMatrix();
}, 120_000);

const near = (a: THREE.Vector3, b: THREE.Vector3) => a.distanceTo(b) < 1e-9;

test("snaps to the exact wall vertex when the hit is a few px away", () => {
  const v = verts[0];
  const hit = v.clone().add(new THREE.Vector3(0.002, 0.002, 0));
  const s = snapPoint(hit, wall, camera, vp, 12);
  expect(s.snap).toBe("vertex");
  expect(near(s.point, v)).toBe(true);
});

test("snaps to a point on an edge, away from vertices", () => {
  const idx = wall.geometry.getIndex()!;
  const [a, b] = [verts[idx.getX(0)], verts[idx.getX(1)]];
  const mid = a.clone().lerp(b, 0.5);
  const s = snapPoint(mid.clone().add(new THREE.Vector3(0, 0.001, 0)), wall, camera, vp, 3);
  expect(s.snap).toBe("edge");
  expect(new THREE.Line3(a, b).closestPointToPoint(s.point, true, new THREE.Vector3()).distanceTo(s.point)).toBeLessThan(1e-9);
});

test("far from features returns the raw surface hit", () => {
  const idx = wall.geometry.getIndex()!;
  let best = { area: 0, c: new THREE.Vector3() };
  for (let t = 0; t < idx.count; t += 3) {
    const [p, q, r] = [0, 1, 2].map((k) => verts[idx.getX(t + k)]);
    const area = new THREE.Triangle(p, q, r).getArea();
    if (area > best.area) best = { area, c: p.clone().add(q).add(r).divideScalar(3) };
  }
  const s = snapPoint(best.c, wall, camera, vp, 1);
  expect(s.snap).toBe("surface");
  expect(near(s.point, best.c)).toBe(true);
});

test("measure between snapped wall corners equals canonical height and thickness", () => {
  const snap = (v: THREE.Vector3) => snapPoint(v.clone().add(new THREE.Vector3(0.001, 0.001, 0)), wall, camera, vp, 6).point;
  const minY = Math.min(...verts.map((v) => v.y));
  const maxY = Math.max(...verts.map((v) => v.y));
  const bottom = verts.filter((v) => Math.abs(v.y - minY) < 1e-9);
  const b0 = bottom[0];
  const top = verts.find((v) => Math.abs(v.y - maxY) < 1e-9 && Math.hypot(v.x - b0.x, v.z - b0.z) < 1e-9)!;
  const h = measure(snap(b0), snap(top));
  expect(h.vertical_mm).toBeCloseTo(wallCanon.height.value, 3);
  expect(h.horizontal_mm).toBeCloseTo(0, 3);
  expect(h.total_mm).toBeCloseTo(wallCanon.height.value, 3);
  const across = bottom.find((v) => Math.abs(v.distanceTo(b0) * 1000 - wallCanon.thickness.value) < 1e-3)!;
  const t = measure(snap(b0), snap(across));
  expect(t.horizontal_mm).toBeCloseTo(wallCanon.thickness.value, 3);
  expect(t.vertical_mm).toBeCloseTo(0, 3);
});
