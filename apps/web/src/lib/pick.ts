// Ray picking over the loaded model. A host wall has a real hole where an opening is, so a
// ray aimed into the aperture passes through the wall; we therefore also test each hosted
// opening's aperture box and prefer it when it is hit before any mesh.
import * as THREE from "three";
import type { ElementData, OpeningData } from "./selection";

export type Pick = { mesh: THREE.Mesh; opening: OpeningData | null; baseY: number; point: THREE.Vector3; shift: THREE.Vector2 };

/** Horizontal (x, z) placement of the floor model a mesh belongs to: plan coordinates are the GLB's, so
 *  an aperture box moves with its floor's offset. Y is already in the mesh's world box. */
const shiftOf = (o: THREE.Object3D): THREE.Vector2 => {
  for (let p: THREE.Object3D | null = o; p; p = p.parent) if (p.userData?.floorRoot) return new THREE.Vector2(p.position.x, p.position.z);
  return new THREE.Vector2();
};

/** Aperture box in three.js metres: span x thickness (+4 mm so the faces are not coplanar). `yaw` turns it
 *  about the vertical axis through its centre: 0 on the axes, the span's plan direction on a diagonal wall. */
export function openingFrame(o: OpeningData, thicknessMm: number, baseY: number, shift = new THREE.Vector2()): { box: THREE.Box3; yaw: number } {
  const [sx, sy] = o.span.start;
  const [ex, ey] = o.span.end;
  const len = Math.hypot(ex - sx, ey - sy) / 1000;
  const h = o.height.value / 1000;
  const t = thicknessMm / 1000 + 0.004;
  const diagonal = Math.abs(ex - sx) > 1e-6 && Math.abs(ey - sy) > 1e-6;
  const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
  const size = new THREE.Vector3(alongX || diagonal ? len : t, h, alongX || diagonal ? t : len);
  // plan (x, y) mm -> three (x, -y) m; sill is above the floor elevation (baseY)
  const centre = new THREE.Vector3((sx + ex) / 2000 + shift.x, baseY + o.sill_height.value / 1000 + h / 2, -(sy + ey) / 2000 + shift.y);
  return { box: new THREE.Box3().setFromCenterAndSize(centre, size), yaw: diagonal ? Math.atan2(ey - sy, ex - sx) : 0 };
}

/** The aperture's box; on a diagonal wall the bounding box of the turned one. */
export function openingBox(o: OpeningData, thicknessMm: number, baseY: number, shift = new THREE.Vector2()): THREE.Box3 {
  const { box, yaw } = openingFrame(o, thicknessMm, baseY, shift);
  if (!yaw) return box;
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  const ex = Math.abs(Math.cos(yaw)) * s.x + Math.abs(Math.sin(yaw)) * s.z;
  const ez = Math.abs(Math.sin(yaw)) * s.x + Math.abs(Math.cos(yaw)) * s.z;
  return new THREE.Box3().setFromCenterAndSize(c, new THREE.Vector3(ex, s.y, ez));
}

/** Where the ray enters the aperture box (turned boxes are hit in their own frame), or null. */
export function rayOpening(ray: THREE.Ray, o: OpeningData, thicknessMm: number, baseY: number, shift = new THREE.Vector2()): THREE.Vector3 | null {
  const { box, yaw } = openingFrame(o, thicknessMm, baseY, shift);
  if (!yaw) return ray.intersectBox(box, new THREE.Vector3());
  const c = box.getCenter(new THREE.Vector3());
  const up = new THREE.Vector3(0, 1, 0);
  const local = new THREE.Ray(
    c.clone().add(ray.origin.clone().sub(c).applyAxisAngle(up, -yaw)),
    ray.direction.clone().applyAxisAngle(up, -yaw),
  );
  const p = local.intersectBox(box, new THREE.Vector3());
  return p ? c.clone().add(p.sub(c).applyAxisAngle(up, yaw)) : null;
}

/** `model`: the pickable floor models (hidden or ghosted floors are left out by the caller). */
export function pickElement(model: THREE.Object3D | THREE.Object3D[], ray: THREE.Ray): Pick | null {
  const roots = [model].flat();
  const caster = new THREE.Raycaster(ray.origin, ray.direction);
  const hit = caster.intersectObjects(roots, true).find((h) => h.object.userData?.type);
  type Cand = { opening: OpeningData; mesh: THREE.Mesh; baseY: number; point: THREE.Vector3; shift: THREE.Vector2; d: number };
  const cands: Cand[] = [];
  roots.forEach((r) => r.traverse((obj) => {
    const ud = obj.userData as ElementData;
    if (ud?.type !== "wall" || !ud.openings?.length) return;
    const mesh = obj as THREE.Mesh;
    // the wall starts at the structural base; sills are measured from the finished floor above it
    const baseY = new THREE.Box3().setFromObject(mesh).min.y + (ud.floor_offset_mm ?? 0) / 1000;
    for (const o of ud.openings) {
      const shift = shiftOf(mesh);
      const p = rayOpening(ray, o, ud.thickness?.value ?? 0, baseY, shift);
      if (p) cands.push({ opening: o, mesh, baseY, point: p, shift, d: ray.origin.distanceTo(p) });
    }
  }));
  const b = cands.sort((x, y) => x.d - y.d)[0];
  if (b && (!hit || b.d <= hit.distance + 1e-6)) return { mesh: b.mesh, opening: b.opening, baseY: b.baseY, point: b.point, shift: b.shift };
  if (!hit) return null;
  const mesh = hit.object as THREE.Mesh;
  return { mesh, opening: null, baseY: new THREE.Box3().setFromObject(mesh).min.y, point: hit.point, shift: shiftOf(mesh) };
}
