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

/** Root cause of the walk-mode glitch: with the default presets wall height = ceiling height, so
 *  the ceiling (zero-thickness, facing down) and the roof's eaves plane (also facing down) are the
 *  SAME plane, as are the wall tops under it. Equal depth in the same direction = z-fighting, seen
 *  flickering overhead as soon as ceilings are drawn (walk mode). True when a ceiling shares a
 *  plane with a roof's underside (within 1 mm). */
export function ceilingMeetsRoof(model: THREE.Object3D): boolean {
  model.updateWorldMatrix(true, true);
  const under = roofs(model).map((r) => new THREE.Box3().setFromObject(r).min.y);
  return meshesOf(model, "ceiling").some((c) => {
    const y = new THREE.Box3().setFromObject(c).min.y;
    return under.some((u) => Math.abs(u - y) < 0.001);
  });
}

/** Pull ceilings towards the camera in depth (polygon offset), so where they share a plane with
 *  the roof underside the ceiling always wins; nothing moves and nothing else changes. */
export function separateCoplanar(model: THREE.Object3D): void {
  for (const c of meshesOf(model, "ceiling")) {
    for (const mat of Array.isArray(c.material) ? c.material : [c.material]) {
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = -2;
      mat.polygonOffsetUnits = -2;
    }
  }
}
