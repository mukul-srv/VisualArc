import * as THREE from "three";
import { expect, test } from "vitest";
import { openingFrame, rayOpening } from "./pick";
import type { OpeningData } from "./selection";

const diag = { span: { start: [0, 0], end: [1000, 1000] }, height: { value: 2100 }, sill_height: { value: 0 } } as unknown as OpeningData;
const axis = { span: { start: [0, 0], end: [1000, 0] }, height: { value: 2100 }, sill_height: { value: 0 } } as unknown as OpeningData;

test("an opening on a diagonal wall is a turned box: a ray across it hits, one beside it (inside its bounding box) misses", () => {
  const across = new THREE.Ray(new THREE.Vector3(-0.2, 1, -1.2), new THREE.Vector3(1, 0, 1).normalize()); // towards the middle
  expect(rayOpening(across, diag, 200, 0)).not.toBeNull();
  const beside = new THREE.Ray(new THREE.Vector3(0.5, 1, -0.1), new THREE.Vector3(1, 0, 0)); // plan (500..,100): far off the wall
  expect(rayOpening(beside, diag, 200, 0)).toBeNull();
  expect(openingFrame(diag, 200, 0).yaw).toBeCloseTo(Math.PI / 4);
});

test("axis-aligned openings are unchanged (no turn)", () => {
  expect(openingFrame(axis, 200, 0).yaw).toBe(0);
  const p = rayOpening(new THREE.Ray(new THREE.Vector3(0.5, 1, 1), new THREE.Vector3(0, 0, -1)), axis, 200, 0);
  expect(p).not.toBeNull();
});
