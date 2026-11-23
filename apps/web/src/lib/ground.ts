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
};
export const GRAVITY = 9.8; // m/s2

export const stepUpLimit = (model: THREE.Object3D) => (maxRiser(model) ?? STEP.fallback) + STEP.slack;

const down = new THREE.Vector3(0, -1, 0);
const caster = new THREE.Raycaster();

/** Highest supported surface at (x, z) that is at most `reach` above `fromY` (any depth below); null
 *  when none. The ray starts just above the reach so a surface at exactly `reach` is hit. */
export function supportAt(x: number, z: number, fromY: number, supports: THREE.Mesh[], reach: number): { y: number; type: string } | null {
  caster.set(new THREE.Vector3(x, fromY + reach + 0.01, z), down);
  caster.near = 0;
  caster.far = 1e5;
  const hit = caster.intersectObjects(supports, false)[0];
  return hit ? { y: hit.point.y, type: hit.object.userData?.type } : null;
}

export type Step = { ok: true; ground: number } | { ok: false };

/** Surfaces that are solid BODIES (down to the floor): a stair is a solid mass, a ramp a wedge. A floor
 *  slab or balcony is a surface, not a body: the one overhead (an upper floor, a balcony above) must not
 *  stop someone walking beneath it. */
const BODY_TYPES = ["stair", "ramp"];

/** Can the walker, with feet at `feetY`, be at (x, z) after moving `travel` metres, and what is the
 *  ground there? Flights and other raised surfaces are SOLID bodies (a stair is a solid mass, a ramp a
 *  wedge down to the floor), whatever lies beneath:
 *   - the highest stair or ramp surface there is more than a step above the feet: blocked. That is the
 *     side or riser of a stair, the side of a ramp, or the space under a ramp (you cannot walk in from
 *     below). Slabs and balconies overhead are not bodies and never block;
 *   - otherwise the ground is the highest surface within a step above the feet, or the baseline `baseY`
 *     when there is none. It may be far below: the walker then falls (see `fall`), nothing stops them
 *     walking off an edge;
 *   - a ramp steeper than the slope limit is refused.
 *  Only the move is judged, so a walker already inside a solid (a stale position) is never stuck: any
 *  move out of it is allowed (the surface is not above them there). */
export function stepOnto(
  x: number, z: number, feetY: number, travel: number, supports: THREE.Mesh[], baseY: number, stepUp: number,
): Step {
  const top = supportAt(x, z, feetY, supports.filter((m) => BODY_TYPES.includes(m.userData?.type)), 1000);
  if (top && top.y > feetY + stepUp) return { ok: false };
  const s = supportAt(x, z, feetY, supports, stepUp);
  if (s && s.type === "ramp" && s.y > feetY && travel > 0 && (s.y - feetY) / travel > STEP.maxSlope) return { ok: false };
  return { ok: true, ground: s ? s.y : baseY };
}

/** One step of gravity towards the ground height: the feet fall (accelerating) and stop on landing; a
 *  ground higher than the feet (a step up) is taken at once, within the step limit already checked.
 *  Pure and frame-rate independent enough for a walker (small `dt`). The eye eases the landing. */
export function fall(feet: number, ground: number, vy: number, dt: number): { feet: number; vy: number } {
  if (feet <= ground) return { feet: ground, vy: 0 };
  const v = vy - GRAVITY * Math.max(0, dt);
  const next = feet + v * Math.max(0, dt);
  return next <= ground ? { feet: ground, vy: 0 } : { feet: next, vy: v };
}

/** Move `current` towards `target` with an exponential approach that does not depend on the frame
 *  rate: after any total time the result is the same however it was cut into frames. Used for the
 *  eye height, so stairs and ramps glide while the ground height itself stays exact. */
export function dampTo(current: number, target: number, dt: number, rate = EYE_RATE): number {
  return target + (current - target) * Math.exp(-rate * Math.max(0, dt));
}

export const EYE_RATE = 14; // 1/s: about 0.2 s to settle
