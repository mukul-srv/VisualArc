// Ground and support heights, free of the DOM so they are unit-testable.
//
// Ground plane: the viewer's grid sits at the structural base of the lowest storey: the underside of
// its slab, which is also where its walls start (canonical/model.py, vertical convention). Slab and
// walls therefore stand on the grid together; the walked floor is the slab top, one slab thickness up.
//
// Support height: for any point, the height of the surface a walker can stand on there, from the
// meshes that carry one (floor boundaries, balconies, stair steps, ramps). Walk mode uses it to
// climb stairs and ramps; Section C (whole-building roaming) can reuse it per floor unchanged.
import * as THREE from "three";

/** Types whose top surface can be walked on. */
export const SUPPORT_TYPES = ["floor_boundary", "balcony", "stair", "ramp"];

/** Level of the grid (the common base of slab and walls), in metres (three.js Y).
 *  `lowestElevationMm`: the lowest floor of the project, when known (several floors share one ground);
 *  otherwise the base of the lowest wall in the model, else the model's own bottom. */
export function groundLevel(model: THREE.Object3D, lowestElevationMm?: number | null): number {
  if (lowestElevationMm != null) return lowestElevationMm / 1000;
  model.updateWorldMatrix(true, true);
  let y = Infinity;
  model.traverse((o) => {
    if ((o as THREE.Mesh).isMesh && o.userData?.type === "wall") y = Math.min(y, new THREE.Box3().setFromObject(o).min.y);
  });
  if (Number.isFinite(y)) return y;
  const all = new THREE.Box3().setFromObject(model);
  return all.isEmpty() ? 0 : all.min.y;
}

export function collectSupports(model: THREE.Object3D): THREE.Mesh[] {
  const out: THREE.Mesh[] = [];
  model.traverse((o) => {
    if ((o as THREE.Mesh).isMesh && SUPPORT_TYPES.includes(o.userData?.type)) out.push(o as THREE.Mesh);
  });
  return out;
}

/** Largest riser in the model (m) from the stairs' own `riser_height`, else null. */
export function maxRiser(model: THREE.Object3D): number | null {
  let r: number | null = null;
  model.traverse((o) => {
    const v = o.userData?.type === "stair" ? o.userData?.riser_height?.value : undefined;
    if (typeof v === "number") r = Math.max(r ?? 0, v / 1000);
  });
  return r;
}

export const STEP = {
  // m: what a walker steps up without a ramp: the stairs' own riser (plus slack for float noise)
  // when the model has stairs, else a kerb-sized default
  slack: 0.02,
  fallback: 0.2,
  maxSlope: 1.0, // rise per metre of travel on a ramp (45 degrees)
  maxDrop: 0.6, // m: deeper than this is a ledge, not a step down
};

export const stepUpLimit = (model: THREE.Object3D) => (maxRiser(model) ?? STEP.fallback) + STEP.slack;

const down = new THREE.Vector3(0, -1, 0);
const caster = new THREE.Raycaster();

/** Highest supported surface at (x, z) that is at most `reach` above `fromY` and at most `maxDrop`
 *  below it; null when none. Ray starts just above the reach so a surface at exactly `reach` hits. */
export function supportAt(x: number, z: number, fromY: number, supports: THREE.Mesh[], reach: number): { y: number; type: string } | null {
  caster.set(new THREE.Vector3(x, fromY + reach + 0.01, z), down);
  caster.near = 0;
  caster.far = reach + 0.01 + STEP.maxDrop;
  const hit = caster.intersectObjects(supports, false)[0];
  return hit ? { y: hit.point.y, type: hit.object.userData?.type } : null;
}

/** New feet height after moving horizontally by `travel` (m) to (x, z), or null when the move is
 *  not allowed (a step higher than the limit, a ramp steeper than the slope limit).
 *  No support under the new point: from at most a step above the baseline (`baseY`) the walker lands
 *  on it (a doorway, the first tread); from higher up it is an edge (the side of a stair or ramp) and
 *  the move is refused, so nobody walks off into thin air or through a stair's side. */
export function resolveHeight(
  x: number, z: number, feetY: number, travel: number, supports: THREE.Mesh[], baseY: number, stepUp: number,
): number | null {
  const s = supportAt(x, z, feetY, supports, stepUp);
  if (!s) {
    const high = supportAt(x, z, feetY, supports, stepUp + 10); // anything taller than a step blocks
    if (high && high.y > feetY + stepUp) return null;
    // nothing within a step down: from the first tread the walker steps down to the floor, but from higher
    // up the side of a stair or ramp is an edge, not a doorway: blocked (a stair has sides)
    return feetY - baseY > stepUp + 1e-6 ? null : baseY;
  }
  if (s.type === "ramp" && travel > 0 && Math.abs(s.y - feetY) / travel > STEP.maxSlope) return null;
  return s.y;
}

/** Move `current` towards `target` with an exponential approach that does not depend on the frame
 *  rate: after any total time the result is the same however it was cut into frames. Used for the
 *  eye height, so stairs and ramps glide while the ground height itself stays exact. */
export function dampTo(current: number, target: number, dt: number, rate = EYE_RATE): number {
  return target + (current - target) * Math.exp(-rate * Math.max(0, dt));
}

export const EYE_RATE = 14; // 1/s: about 0.2 s to settle
