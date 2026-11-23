// Roof visibility and the walk-mode depth fix, free of the DOM so they are unit-testable.
import * as THREE from "three";

const meshesOf = (model: THREE.Object3D, type: string) => {
  const out: THREE.Mesh[] = [];
  model.traverse((o) => {
    if ((o as THREE.Mesh).isMesh && o.userData?.type === type) out.push(o as THREE.Mesh);
  });
  return out;
};

export const roofs = (model: THREE.Object3D) => meshesOf(model, "roof");
export const hasRoof = (model: THREE.Object3D) => roofs(model).length > 0;

export function setRoofVisible(model: THREE.Object3D, visible: boolean): void {
  for (const r of roofs(model)) r.visible = visible;
}

/** Which ceilings are drawn (in walk mode, the only mode that draws them) for the roof toggle. With the
 *  default presets wall height = ceiling height, so the ceiling and the roof's underside are the same
 *  plane (within 1 mm): drawn together they would z-fight and the ceiling would hide the roof.
 *  - roof ON and the ceiling shares the roof's underside plane (the default presets): the ceiling is
 *    hidden, the roof's own underside is what you see overhead: no second surface in that plane, so
 *    no z-fighting, and the roof is visible from inside;
 *  - roof ON and the ceiling is lower than the roof: the ceiling is drawn (a real lid under the roof);
 *  - roof OFF: ceilings are hidden, so the room is open to the sky like in the orbit view. */
export function applyCeilingVisibility(model: THREE.Object3D, roofOn: boolean): void {
  model.updateWorldMatrix(true, true);
  const under = roofs(model).map((r) => new THREE.Box3().setFromObject(r).min.y);
  for (const c of meshesOf(model, "ceiling")) {
    const y = new THREE.Box3().setFromObject(c).min.y;
    const sharesPlane = under.some((u) => Math.abs(u - y) < 0.001);
    c.visible = roofOn && !sharesPlane;
  }
}
