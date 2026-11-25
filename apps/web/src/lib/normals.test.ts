import { expect, test } from "vitest";
import * as THREE from "three";
import { ensureNormals, ensureUVs } from "./normals";

test("adds flat normals to meshes without them and leaves the rest alone", () => {
  const bare = new THREE.BoxGeometry(2, 2, 2);
  bare.deleteAttribute("normal");
  const indexed = new THREE.Mesh(bare, new THREE.MeshStandardMaterial());
  const withN = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial());
  const keep = withN.geometry;
  const root = new THREE.Group().add(indexed, withN);
  expect(ensureNormals(root)).toBe(1);
  expect(withN.geometry).toBe(keep);
  const g = indexed.geometry;
  expect(g.index).toBeNull();
  const n = g.getAttribute("normal");
  expect(n.count).toBe(g.getAttribute("position").count);
  // every triangle's three vertices share its face normal: nothing is smoothed across the cube's edges
  for (let t = 0; t < n.count; t += 3) {
    const a = new THREE.Vector3().fromBufferAttribute(n, t);
    expect(Math.abs(a.length() - 1)).toBeLessThan(1e-6);
    for (const k of [1, 2]) expect(new THREE.Vector3().fromBufferAttribute(n, t + k).distanceTo(a)).toBeLessThan(1e-6);
  }
  expect(ensureNormals(root)).toBe(0); // idempotent
});

test("adds box-projected metre UVs to meshes without them, keeps existing ones", () => {
  const bare = new THREE.BoxGeometry(2, 4, 6);
  bare.deleteAttribute("uv");
  const mesh = new THREE.Mesh(bare, new THREE.MeshStandardMaterial());
  const withUv = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial());
  const keep = withUv.geometry;
  const root = new THREE.Group().add(mesh, withUv);
  expect(ensureUVs(root)).toBe(1);
  expect(withUv.geometry).toBe(keep);
  const uv = mesh.geometry.getAttribute("uv");
  expect(uv.count).toBe(mesh.geometry.getAttribute("position").count);
  let max = 0;
  for (let i = 0; i < uv.count; i++) max = Math.max(max, Math.abs(uv.getX(i)), Math.abs(uv.getY(i)));
  expect(max).toBeCloseTo(3, 5); // metres: the box is 6 long, so UVs span +-3, not 0..1
  expect(ensureUVs(root)).toBe(0);
});
