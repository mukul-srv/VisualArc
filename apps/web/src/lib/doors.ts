// Door interaction, free of the DOM so it is unit-testable.
//
// The GLB carries each door's leaf as its own node (`opening_part`, part "leaf") and the full
// opening record (span, swing, frame width) in its userData, so the leaf can be swung about its
// hinge without the viewer re-deriving any geometry rule. A door without swing data (no arc
// symbol in the drawing, so hinge and side are unknown) is never guessed: it does nothing.
// Windows have no swing data in the model and are not interactive.
import * as THREE from "three";
import type { OpeningData } from "./selection";

export const DOOR = {
  speed: 2.5, // rad/s
  open: Math.PI / 2, // a door opens a quarter turn
  reach: 1.6, // m: how close the walker must be (E key / tap in walk mode)
  clear: 0.6, // m: a door cannot close while the walker stands this close to its opening
};

type Plan = [number, number];
const TOWARD: Record<string, Plan> = { "+x": [1, 0], "-x": [-1, 0], "+y": [0, 1], "-y": [0, -1] };

export type Hinge = { pivot: THREE.Vector3; angle: number };

/** Pivot (three.js metres, on the wall centreline) and the signed quarter-turn about +Y that swings
 *  the closed leaf towards `opens_toward`. Null when the opening has no swing record or is no door. */
export function hingeOf(o: OpeningData): Hinge | null {
  if (o.kind !== "door" || !o.swing) return null;
  const [sx, sy] = o.span.start;
  const [ex, ey] = o.span.end;
  const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
  const fw = o.detail?.frame_width.value ?? 0; // the leaf is hung inside the frame
  const lo = alongX ? Math.min(sx, ex) : Math.min(sy, ey);
  const hi = alongX ? Math.max(sx, ex) : Math.max(sy, ey);
  const hingeAtStart = o.swing.hinge === "start";
  const a = hingeAtStart ? lo + fw : hi - fw; // along the wall, plan mm
  const u: Plan = alongX ? [hingeAtStart ? 1 : -1, 0] : [0, hingeAtStart ? 1 : -1]; // pivot -> free edge, plan
  const t = TOWARD[o.swing.opens_toward];
  // plan (x, y) -> three (x, -y); rotation about +Y by q maps (x, z) to (x cos q + z sin q, -x sin q + z cos q)
  const [ux, uz] = [u[0], -u[1]];
  const [tx, tz] = [t[0], -t[1]];
  const angle = Math.abs(uz - tx) < 1e-9 && Math.abs(-ux - tz) < 1e-9 ? Math.PI / 2 : -Math.PI / 2;
  const [px, py] = alongX ? [a, (sy + ey) / 2] : [(sx + ex) / 2, a];
  return { pivot: new THREE.Vector3(px / 1000, 0, -py / 1000), angle };
}

export type Door = {
  opening: OpeningData;
  leaf: THREE.Mesh;
  pivot: THREE.Group;
  hinge: Hinge;
  open: boolean; // the target state
  angle: number; // current, 0 = closed
};

/** Every door leaf in the model with swing data, re-hung on a pivot at its hinge. */
export function buildDoors(model: THREE.Object3D): Door[] {
  const leaves: THREE.Mesh[] = [];
  model.updateWorldMatrix(true, true);
  model.traverse((o) => {
    const ud = o.userData;
    if (ud?.type === "opening_part" && ud.part === "leaf" && ud.opening && (o as THREE.Mesh).isMesh) leaves.push(o as THREE.Mesh);
  });
  const doors: Door[] = [];
  for (const leaf of leaves) {
    // (collected first: re-parenting while traversing would visit the leaf again under its pivot)
    const hinge = hingeOf(leaf.userData.opening as OpeningData);
    if (!hinge) continue;
    const pivot = new THREE.Group();
    pivot.position.copy(hinge.pivot);
    (leaf.parent ?? model).add(pivot);
    pivot.updateMatrixWorld(true);
    pivot.attach(leaf); // keeps the leaf where it is, now rotating about the hinge
    doors.push({ opening: leaf.userData.opening, leaf, pivot, hinge, open: false, angle: 0 });
  }
  return doors;
}

/** Why an opening cannot be toggled (shown to the user), or null when it can. */
export function whyNoToggle(o: OpeningData | null | undefined, doors: Door[]): string | null {
  if (!o) return null;
  if (o.kind === "window") return "Windows do not open in this model (no hinge or sliding data).";
  if (!doors.some((d) => d.opening.id === o.id)) return "This door has no swing arc in the drawing, so its hinge side is unknown and it stays closed.";
  return null;
}

export const doorFor = (doors: Door[], id: string) => doors.find((d) => d.opening.id === id) ?? null;

export function toggle(d: Door): void {
  d.open = !d.open;
}

/** Advance every door's leaf towards its target; true when anything moved. */
export function animate(doors: Door[], dt: number): boolean {
  let moved = false;
  for (const d of doors) {
    const goal = d.open ? DOOR.open : 0;
    if (d.angle === goal) continue;
    const step = DOOR.speed * dt;
    d.angle = d.angle < goal ? Math.min(goal, d.angle + step) : Math.max(goal, d.angle - step);
    d.pivot.rotation.y = d.hinge.angle * (d.angle / DOOR.open);
    d.pivot.updateMatrixWorld(true);
    moved = true;
  }
  return moved;
}

/** A closed door is solid; one that is open (or opening) is passable at once, so a walker is never
 *  caught in a leaf that is still swinging. */
export const blocking = (doors: Door[]) => doors.filter((d) => !d.open).map((d) => d.leaf);

/** Horizontal distance (m) from `p` to the door's opening (its span on the wall centreline). */
export function distanceToOpening(d: Door, p: THREE.Vector3): number {
  const [sx, sy] = d.opening.span.start;
  const [ex, ey] = d.opening.span.end;
  const a = new THREE.Vector2(sx / 1000, -sy / 1000);
  const b = new THREE.Vector2(ex / 1000, -ey / 1000);
  const q = new THREE.Vector2(p.x, p.z);
  return new THREE.Line3(new THREE.Vector3(a.x, 0, a.y), new THREE.Vector3(b.x, 0, b.y))
    .closestPointToPoint(new THREE.Vector3(q.x, 0, q.y), true, new THREE.Vector3())
    .distanceTo(new THREE.Vector3(q.x, 0, q.y));
}

export function nearestDoor(doors: Door[], p: THREE.Vector3, reach = DOOR.reach): Door | null {
  let best: Door | null = null;
  let bd = reach;
  for (const d of doors) {
    const dist = distanceToOpening(d, p);
    if (dist <= bd) [best, bd] = [d, dist];
  }
  return best;
}

/** A door that is open is only closed when the walker is not standing in or at its opening. */
export const canClose = (d: Door, p: THREE.Vector3) => distanceToOpening(d, p) > DOOR.clear;
