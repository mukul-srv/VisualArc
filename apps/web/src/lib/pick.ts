// Ray picking over the loaded model. A host wall has a real hole where an opening is, so a
// ray aimed into the aperture passes through the wall; we therefore also test each hosted
// opening's aperture box and prefer it when it is hit before any mesh.
import * as THREE from "three";
import type { ElementData, OpeningData } from "./selection";

export type Pick = { mesh: THREE.Mesh; opening: OpeningData | null; baseY: number; point: THREE.Vector3 };

/** Aperture box in three.js metres: span x thickness (+4 mm so the faces are not coplanar). */
export function openingBox(o: OpeningData, thicknessMm: number, baseY: number): THREE.Box3 {
  const [sx, sy] = o.span.start;
  const [ex, ey] = o.span.end;
  const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
  const len = Math.hypot(ex - sx, ey - sy) / 1000;
  const h = o.height.value / 1000;
  const t = thicknessMm / 1000 + 0.004;
  const size = new THREE.Vector3(alongX ? len : t, h, alongX ? t : len);
  // plan (x, y) mm -> three (x, -y) m; sill is above the floor elevation (baseY)
  const centre = new THREE.Vector3((sx + ex) / 2000, baseY + o.sill_height.value / 1000 + h / 2, -(sy + ey) / 2000);
  return new THREE.Box3().setFromCenterAndSize(centre, size);
}

export function pickElement(model: THREE.Object3D, ray: THREE.Ray): Pick | null {
  const caster = new THREE.Raycaster(ray.origin, ray.direction);
  const hit = caster.intersectObject(model, true).find((h) => h.object.userData?.type);
  type Cand = { opening: OpeningData; mesh: THREE.Mesh; baseY: number; point: THREE.Vector3; d: number };
  const cands: Cand[] = [];
  model.traverse((obj) => {
    const ud = obj.userData as ElementData;
    if (ud?.type !== "wall" || !ud.openings?.length) return;
    const mesh = obj as THREE.Mesh;
    const baseY = new THREE.Box3().setFromObject(mesh).min.y;
    for (const o of ud.openings) {
      const p = ray.intersectBox(openingBox(o, ud.thickness?.value ?? 0, baseY), new THREE.Vector3());
      if (p) cands.push({ opening: o, mesh, baseY, point: p, d: ray.origin.distanceTo(p) });
    }
  });
  const b = cands.sort((x, y) => x.d - y.d)[0];
  if (b && (!hit || b.d <= hit.distance + 1e-6)) return { mesh: b.mesh, opening: b.opening, baseY: b.baseY, point: b.point };
  if (!hit) return null;
  const mesh = hit.object as THREE.Mesh;
  return { mesh, opening: null, baseY: new THREE.Box3().setFromObject(mesh).min.y, point: hit.point };
}
