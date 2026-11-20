import { expect, test } from "vitest";
import * as THREE from "three";

test("three loads and builds a scene", () => {
  const scene = new THREE.Scene();
  scene.add(new THREE.GridHelper(10, 10));
  expect(scene.children).toHaveLength(1);
});
