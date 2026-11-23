import * as THREE from "three";
import { expect, test } from "vitest";
import { distanceToOpening, type Door } from "./doors";
import { setGhost } from "./ghost";
import { pickElement } from "./pick";

// A floor model moved by its plan offset: everything stated in plan coordinates (apertures, doors) must move with it.
const opening = {
  id: "o1", kind: "door", span: { start: [0, 0], end: [1000, 0] }, height: { value: 2000 }, sill_height: { value: 0 },
};
function floor(at: [number, number, number]) {
  const root = new THREE.Group();
  root.userData.floorRoot = true;
  const wall = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.1), new THREE.MeshStandardMaterial());
  wall.position.set(100, 0, 0); // far from the aperture, so only the aperture box is hit
  wall.userData = { type: "wall", thickness: { value: 200 }, floor_offset_mm: 0, openings: [opening] };
  root.add(wall);
  root.position.set(...at);
  root.updateMatrixWorld(true);
  return root;
}

test("an aperture is picked where its floor was moved to, not where the plan says", () => {
  const root = floor([5, 0, 3]);
  const at = (x: number, z: number) => pickElement([root], new THREE.Ray(new THREE.Vector3(x, 1, z + 5), new THREE.Vector3(0, 0, -1)));
  expect(at(5.5, 3)?.opening?.id).toBe("o1");
  expect(at(5.5, 3)?.shift.toArray()).toEqual([5, 3]);
  expect(at(0.5, 0)).toBeNull();
});

test("door distance is measured in the floor's own plan frame", () => {
  const d = { opening, root: floor([5, 0, 3]) } as unknown as Door;
  expect(distanceToOpening(d, new THREE.Vector3(5.5, 0, 3.2))).toBeCloseTo(0.2);
  expect(distanceToOpening({ opening } as unknown as Door, new THREE.Vector3(0.5, 0, 0.2))).toBeCloseTo(0.2);
});

test("ghosting is reversible and marks the floor as not pickable", () => {
  const root = floor([0, 0, 0]);
  const mat = (root.children[0] as THREE.Mesh).material as THREE.Material;
  setGhost(root, true);
  expect([mat.transparent, mat.opacity, root.userData.ghost]).toEqual([true, 0.12, true]);
  setGhost(root, false);
  expect([mat.transparent, mat.opacity, root.userData.ghost]).toEqual([false, 1, false]);
});
