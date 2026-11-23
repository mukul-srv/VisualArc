// First-person walk mode (T23): collision against the REAL wall meshes, so doors and
// windows behave as modelled (the viewer never re-derives geometry rules).
//
// A player is a vertical stack of horizontal probes: at several heights and three lateral
// offsets, a ray is cast in the direction of travel. A move is blocked if any probe hits a
// wall/junction within (step + radius). Heights are chosen so a door aperture (sill 0)
// lets the player through while a window (sill 0.9 m) does not: the low probes hit the
// wall below the sill.
// shortcut: radius is approximated by 7 lateral rays 75 mm apart (not a swept capsule), so
// an object narrower than 75 mm could be missed; walls are >= 50 mm, so a 50-75 mm free
// stub could slip between rays. Upgrade to a swept test if such partitions or columns are
// supported. Known by design: a window whose sill is below 0.3 m and head above 1.6 m
// behaves like a door (the probes cannot tell them apart).
import * as THREE from "three";

export const WALK = {
  radius: 0.25, // m, body radius
  eye: 1.6, // m above the floor
  probeHeights: [0.3, 0.6, 1.2, 1.6, 1.75], // m above the floor (1.75: just above the eye, so a low lintel is hit)
  lateral: [-0.9, -0.6, -0.3, 0, 0.3, 0.6, 0.9], // x radius; spacing 75 mm < a 100 mm wall stub
  speed: 2.0, // m/s
};

/** Ceilings live on their own layer: three's Raycaster only tests layer 0, so they are
 *  never picked, measured, or hit by the spawn/collision rays; only a camera that enables
 *  this layer (walk mode) draws them. */
export const CEILING_LAYER = 1;

export function layerCeilings(model: THREE.Object3D): void {
  model.traverse((o) => {
    if (o.userData?.type === "ceiling") o.layers.set(CEILING_LAYER);
  });
}

/** Bounding box of the model without ceilings, so orbit limits and plan framing do not
 *  depend on geometry that is hidden in those views. */
export function modelBox(model: THREE.Object3D): THREE.Box3 {
  const box = new THREE.Box3();
  model.updateWorldMatrix(true, true);
  model.traverse((o) => {
    if ((o as THREE.Mesh).isMesh && o.userData?.type !== "ceiling") box.expandByObject(o);
  });
  return box;
}

/** Types the player cannot walk through. Stairs and ramps are not here: their treads and slope are
 *  walked ON (lib/ground.ts), and their sides are edges (a raised walker cannot step off them). */
export const OBSTRUCTIONS = ["wall", "junction", "column", "balcony_railing"];

/** Solid meshes the player collides with: walls, junctions, columns and balcony railings (never the
 *  floor plane or a walkable surface). */
export function collectColliders(model: THREE.Object3D): THREE.Mesh[] {
  const out: THREE.Mesh[] = [];
  model.traverse((o) => {
    if (OBSTRUCTIONS.includes(o.userData?.type) && (o as THREE.Mesh).isMesh) out.push(o as THREE.Mesh);
  });
  return out;
}

/** Rays only hit front faces by default; a player that ends up flush inside a wall must
 *  still see its back faces. Returns a function that restores the original sides. */
export function makeDoubleSided(colliders: THREE.Mesh[]): () => void {
  const saved = new Map<THREE.Material, THREE.Side>();
  for (const m of colliders) {
    for (const mat of Array.isArray(m.material) ? m.material : [m.material]) {
      if (!saved.has(mat)) saved.set(mat, mat.side);
      mat.side = THREE.DoubleSide;
    }
  }
  return () => saved.forEach((side, mat) => (mat.side = side));
}

const caster = new THREE.Raycaster();

function blocked(pos: THREE.Vector3, dir: THREE.Vector3, dist: number, floorY: number, colliders: THREE.Mesh[]): boolean {
  const perp = new THREE.Vector3(-dir.z, 0, dir.x);
  caster.near = 0;
  caster.far = dist + WALK.radius;
  for (const h of WALK.probeHeights) {
    for (const k of WALK.lateral) {
      const off = k * WALK.radius;
      const origin = new THREE.Vector3(pos.x + perp.x * off, floorY + h, pos.z + perp.z * off);
      caster.set(origin, dir);
      if (caster.intersectObjects(colliders, false).length) return true;
    }
  }
  return false;
}

/** Move `pos` (feet position, y = floor level) by the horizontal `delta`, axis by axis so
 *  the player slides along walls. Mutates and returns `pos`. */
export function moveWithCollision(
  pos: THREE.Vector3,
  delta: THREE.Vector2,
  floorY: number,
  colliders: THREE.Mesh[],
): THREE.Vector3 {
  // m: small sub-steps so sliding along a wall is resolved in fine increments (a single
  // long step cannot tunnel anyway: each probe ray covers the whole step)
  const MAX_STEP = 0.1;
  const n = Math.max(1, Math.ceil(Math.hypot(delta.x, delta.y) / MAX_STEP));
  const sx = delta.x / n;
  const sz = delta.y / n;
  for (let i = 0; i < n; i++) {
    if (sx !== 0 && !blocked(pos, new THREE.Vector3(Math.sign(sx), 0, 0), Math.abs(sx), floorY, colliders)) pos.x += sx;
    if (sz !== 0 && !blocked(pos, new THREE.Vector3(0, 0, Math.sign(sz)), Math.abs(sz), floorY, colliders)) pos.z += sz;
  }
  return pos;
}

/** A point inside the largest floor boundary (area-weighted centroid, falling back to the
 *  centroid of its largest triangle when the centroid lies outside, e.g. an L-shaped room). */
export function spawnPoint(model: THREE.Object3D): { pos: THREE.Vector3; floorY: number } | null {
  let best: { mesh: THREE.Mesh; area: number } | null = null;
  model.traverse((o) => {
    if (o.userData?.type !== "floor_boundary" || !(o as THREE.Mesh).isMesh) return;
    const mesh = o as THREE.Mesh;
    const area = new THREE.Box3().setFromObject(mesh).getSize(new THREE.Vector3());
    const a = area.x * area.z;
    if (!best || a > best.area) best = { mesh, area: a };
  });
  const found = best as { mesh: THREE.Mesh; area: number } | null;
  if (!found) return null;
  const mesh = found.mesh;
  mesh.updateWorldMatrix(true, false);
  const g = mesh.geometry;
  const p = g.getAttribute("position");
  const idx = g.getIndex();
  const tri = (i: number) => {
    const ids = idx ? [idx.getX(3 * i), idx.getX(3 * i + 1), idx.getX(3 * i + 2)] : [3 * i, 3 * i + 1, 3 * i + 2];
    return ids.map((k) => new THREE.Vector3().fromBufferAttribute(p, k).applyMatrix4(mesh.matrixWorld));
  };
  const count = idx ? idx.count / 3 : p.count / 3;
  const centroid = new THREE.Vector3();
  let total = 0;
  let largest = { area: -1, c: new THREE.Vector3() };
  for (let i = 0; i < count; i++) {
    const [a, b, c] = tri(i);
    const area = new THREE.Triangle(a, b, c).getArea();
    const tc = a.clone().add(b).add(c).divideScalar(3);
    centroid.addScaledVector(tc, area);
    total += area;
    if (area > largest.area) largest = { area, c: tc };
  }
  if (total === 0) return null;
  centroid.divideScalar(total);
  const floorY = new THREE.Box3().setFromObject(mesh).min.y;
  // inside test: a downward ray from above the centroid must hit this boundary mesh
  const down = new THREE.Raycaster(new THREE.Vector3(centroid.x, floorY + 1, centroid.z), new THREE.Vector3(0, -1, 0));
  const m = mesh.material as THREE.Material;
  const side = m.side;
  m.side = THREE.DoubleSide;
  const inside = down.intersectObject(mesh, false).length > 0;
  m.side = side;
  const at = inside ? centroid : largest.c;
  return { pos: new THREE.Vector3(at.x, floorY, at.z), floorY };
}
