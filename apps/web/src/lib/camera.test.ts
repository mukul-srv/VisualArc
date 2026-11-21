import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { beforeAll, expect, test } from "vitest";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { orbitLimits, planFrustum } from "./camera";

const root = path.resolve(__dirname, "../../../..");
let box: THREE.Box3;

beforeAll(async () => {
  const out = mkdtempSync(path.join(tmpdir(), "camera-"));
  execFileSync(
    "uv",
    ["run", "python", "-m", "api.cli", "build", path.join(root, "fixtures/input/fixture_a.dxf"), "--wall-height", "3000", "--out", out],
    { cwd: path.join(root, "services/api"), stdio: "pipe" },
  );
  const buf = readFileSync(path.join(out, "fixture_a.glb"));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  const gltf = await new GLTFLoader().parseAsync(ab, "");
  box = new THREE.Box3().setFromObject(gltf.scene);
}, 120_000);

test.each([0.5, 1, 2.5])("plan frustum contains the model footprint, aspect %s", (aspect) => {
  const f = planFrustum(box, aspect, 0.1);
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  expect((f.right - f.left) / (f.top - f.bottom)).toBeCloseTo(aspect, 6);
  expect(f.right - f.left).toBeGreaterThanOrEqual(s.x);
  expect(f.top - f.bottom).toBeGreaterThanOrEqual(s.z);
  expect(f.position.x).toBeCloseTo(c.x, 6);
  expect(f.position.z).toBeCloseTo(c.z, 6);
  expect(f.position.y).toBeGreaterThan(box.max.y);
  // whole model depth lies between near and far along the view axis
  expect(f.position.y - f.near).toBeGreaterThanOrEqual(box.max.y);
  expect(f.position.y - f.far).toBeLessThanOrEqual(box.min.y);
});

test("larger margin gives a larger frustum", () => {
  expect(planFrustum(box, 1.5, 0.3).top).toBeGreaterThan(planFrustum(box, 1.5, 0.05).top);
});

test("orbit limits scale with the model and keep the camera above ground", () => {
  const l = orbitLimits(box);
  const diag = box.getSize(new THREE.Vector3()).length();
  expect(l.minDistance).toBeGreaterThan(0);
  expect(l.minDistance).toBeLessThan(diag);
  expect(l.maxDistance).toBeGreaterThan(diag);
  expect(l.maxPolarAngle).toBeLessThan(Math.PI / 2);
  expect(l.maxPolarAngle).toBeGreaterThan(Math.PI / 3);
});
