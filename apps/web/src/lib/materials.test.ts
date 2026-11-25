import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, vi } from "vitest";
import * as THREE from "three";
import { applyMaterials, libraryFor, LIBRARY, materialKey, parseMaterials, putMaterials, textureCache } from "./materials";

const stub = () => new THREE.Texture();

test("library index: every set has its three maps and suits some element", () => {
  expect(LIBRARY.length).toBeGreaterThanOrEqual(10);
  for (const m of LIBRARY) {
    expect(m.tile_m).toBeGreaterThan(0);
    expect(m.suits.length).toBeGreaterThan(0);
    for (const f of ["color", "normal", "roughness"]) expect(existsSync(resolve(__dirname, `../../public/materials/${m.id}/${f}.jpg`))).toBe(true);
  }
  expect(libraryFor("roof").map((m) => m.id)).toContain("roof-tile");
  expect(libraryFor("wall").every((m) => m.suits.includes("wall"))).toBe(true);
});

test("parseMaterials drops unknown ids and non-strings", () => {
  expect(parseMaterials({ "f/a": "brick", "f/b": "gold", "f/c": 3 })).toEqual({ "f/a": "brick" });
  expect(parseMaterials(null)).toEqual({});
});

test("texture cache loads once per set, tiles at real scale, disposes", () => {
  const load = vi.fn(stub);
  const cache = textureCache(load);
  const brick = LIBRARY.find((m) => m.id === "brick")!;
  const a = cache.get(brick);
  expect(cache.get(brick)).toBe(a);
  expect(load).toHaveBeenCalledTimes(3);
  expect(a.map.repeat.x).toBeCloseTo(1 / brick.tile_m);
  expect(a.map.colorSpace).toBe(THREE.SRGBColorSpace);
  expect(a.normalMap.colorSpace).not.toBe(THREE.SRGBColorSpace);
  const spy = vi.spyOn(a.map, "dispose");
  cache.dispose();
  expect(spy).toHaveBeenCalled();
});

test("applyMaterials swaps, keeps the original, restores when the choice goes", () => {
  const original = new THREE.MeshStandardMaterial({ color: 0x123456 });
  const wall = new THREE.Mesh(new THREE.BoxGeometry(), original);
  wall.userData = { id: "w-1" };
  const other = new THREE.Mesh(new THREE.BoxGeometry(), original);
  other.userData = { id: "w-2" };
  const root = new THREE.Group().add(wall, other);
  const cache = textureCache(stub);
  const pick = { [materialKey("floor-1", "w-1")]: "brick" };
  applyMaterials(root, "floor-1", pick, cache);
  const m = wall.material as THREE.MeshStandardMaterial;
  expect(m).not.toBe(original);
  expect(m.map).not.toBeNull();
  expect(m.normalMap).not.toBeNull();
  expect(other.material).toBe(original); // untouched
  applyMaterials(root, "floor-1", pick, cache);
  expect(wall.material).toBe(m); // same choice: no new material
  applyMaterials(root, "floor-1", {}, cache); // back to default
  expect(wall.material).toBe(original);
});

test("putMaterials sends the whole map", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({ materials: { "f/a": "tile" }, version: 3 })));
  const r = await putMaterials("p1", { "f/a": "tile" }, f as unknown as typeof fetch);
  expect(r.ok).toBe(true);
  const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/v1/projects/p1/materials");
  expect(init.method).toBe("PUT");
  expect(JSON.parse(init.body as string)).toEqual({ materials: { "f/a": "tile" } });
});
