import { expect, test } from "vitest";
import * as THREE from "three";
import { ceilingMeetsRoof, hasRoof, separateCoplanar, setRoofVisible } from "./roof";

const slab = (type: string, y: number) => {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(5, 5), new THREE.MeshBasicMaterial());
  m.rotation.x = Math.PI / 2;
  m.position.y = y;
  m.userData = { type };
  return m;
};
const model = (ceilingY: number) => {
  const g = new THREE.Group();
  g.add(slab("ceiling", ceilingY), slab("roof", 2.7), slab("wall", 0));
  g.updateMatrixWorld(true);
  return g;
};

test("a ceiling at the wall height shares a plane with the roof underside (the walk-mode z-fight)", () => {
  expect(ceilingMeetsRoof(model(2.7))).toBe(true); // default presets: wall height = ceiling height
  expect(ceilingMeetsRoof(model(2.4))).toBe(false);
});

test("separateCoplanar offsets only the ceiling's depth", () => {
  const g = model(2.7);
  separateCoplanar(g);
  const mat = (t: string) => {
    let out: THREE.Material | null = null;
    g.traverse((o) => o.userData.type === t && (out = (o as THREE.Mesh).material as THREE.Material));
    return out as unknown as THREE.Material;
  };
  expect(mat("ceiling").polygonOffset).toBe(true);
  expect(mat("ceiling").polygonOffsetFactor).toBeLessThan(0);
  expect(mat("roof").polygonOffset).toBe(false);
});

test("the roof toggle hides and shows only roof meshes", () => {
  const g = model(2.4);
  expect(hasRoof(g)).toBe(true);
  setRoofVisible(g, false);
  const vis: Record<string, boolean> = {};
  g.traverse((o) => o.userData.type && (vis[o.userData.type] = o.visible));
  expect(vis).toEqual({ ceiling: true, roof: false, wall: true });
  setRoofVisible(g, true);
  expect(hasRoof(g)).toBe(true);
  expect(hasRoof(new THREE.Group())).toBe(false);
});
