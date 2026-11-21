import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { beforeAll, expect, test } from "vitest";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const root = path.resolve(__dirname, "../../../..");
let gltf: { scene: THREE.Group };
let ids: string[];

beforeAll(async () => {
  // Build fresh from the fixture so the test never depends on a stale copied GLB.
  const out = mkdtempSync(path.join(tmpdir(), "glb-smoke-"));
  execFileSync(
    "uv",
    ["run", "python", "-m", "api.cli", "build", path.join(root, "fixtures/input/fixture_a.dxf"), "--wall-height", "3000", "--ceiling-height", "3000", "--out", out],
    { cwd: path.join(root, "services/api"), stdio: "pipe" },
  );
  const buf = readFileSync(path.join(out, "fixture_a.glb"));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  gltf = await new GLTFLoader().parseAsync(ab, "");
  const f = JSON.parse(
    readFileSync(path.join(root, "fixtures/expected/fixture_a.canonical.json"), "utf8"),
  ).buildings[0].floors[0];
  ids = [...f.walls, ...f.junctions, ...f.boundaries, ...f.ceilings].map((e: { id: string }) => e.id);
}, 120_000);

test("fixture A: node/mesh names match canonical element ids", () => {
  const meshes: THREE.Mesh[] = [];
  gltf.scene.traverse((o) => o instanceof THREE.Mesh && meshes.push(o));
  expect(meshes.map((m) => m.name).sort()).toEqual([...ids].sort());
});

test("fixture A: bounds are 8.20 x 5.20 x 3.00 m, Y-up, plan Y -> -Z", () => {
  const box = new THREE.Box3().setFromObject(gltf.scene);
  const size = box.getSize(new THREE.Vector3());
  expect(size.x).toBeCloseTo(8.2, 3);
  expect(size.y).toBeCloseTo(3.0, 3);
  expect(size.z).toBeCloseTo(5.2, 3);
  expect(box.min.y).toBeCloseTo(0, 3);
  expect(box.max.z).toBeCloseTo(0, 3); // plan Y >= 0 lands on -Z
});

test("fixture A: extras survive into userData", () => {
  const wall = gltf.scene.getObjectByName("wall-001")!;
  const ud = wall.userData;
  expect(ud.id).toBe("wall-001");
  expect(ud.type).toBe("wall");
  expect(ud.floor_id).toBeTruthy();
  expect(ud.height.source).toBe("user_provided");
  expect(ud.sources.length).toBeGreaterThan(0);
});
