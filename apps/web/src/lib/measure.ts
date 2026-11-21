// Pure measuring helpers. Viewer-derived values only: never written back to source data.
// Scene metres (Y up, plan y -> -z) -> mm, same convention as selection.ts.
import * as THREE from "three";

export type SnapKind = "vertex" | "edge" | "surface";
export type Snap = { point: THREE.Vector3; snap: SnapKind };
export type Measurement = { total_mm: number; horizontal_mm: number; vertical_mm: number };

/** Nearest mesh vertex within pxTol screen px wins, else nearest mesh edge point within pxTol, else the raw hit. */
export function snapPoint(
  hit: THREE.Vector3,
  mesh: THREE.Mesh,
  camera: THREE.Camera,
  viewportPx: { width: number; height: number },
  pxTol: number,
): Snap {
  mesh.updateWorldMatrix(true, false);
  camera.updateMatrixWorld();
  const toPx = (p: THREE.Vector3) => {
    const n = p.clone().project(camera);
    return n.z > 1 || n.z < -1 ? null : new THREE.Vector2((n.x * viewportPx.width) / 2, (n.y * viewportPx.height) / 2);
  };
  const hitPx = toPx(hit);
  if (!hitPx) return { point: hit.clone(), snap: "surface" };
  const pos = mesh.geometry.getAttribute("position");
  const index = mesh.geometry.getIndex();
  const vert = (i: number) => new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
  const tri = index ? index.count / 3 : pos.count / 3;
  const at = (k: number) => (index ? index.getX(k) : k);

  let bestV: { p: THREE.Vector3; d: number } | null = null;
  for (let i = 0; i < pos.count; i++) {
    const p = vert(i);
    const s = toPx(p);
    const d = s ? s.distanceTo(hitPx) : Infinity;
    if (d <= pxTol && (!bestV || d < bestV.d)) bestV = { p, d };
  }
  if (bestV) return { point: bestV.p, snap: "vertex" };

  let bestE: { p: THREE.Vector3; d: number } | null = null;
  const line = new THREE.Line3();
  for (let t = 0; t < tri; t++) {
    for (let e = 0; e < 3; e++) {
      line.set(vert(at(t * 3 + e)), vert(at(t * 3 + ((e + 1) % 3))));
      const p = line.closestPointToPoint(hit, true, new THREE.Vector3());
      const s = toPx(p);
      const d = s ? s.distanceTo(hitPx) : Infinity;
      if (d <= pxTol && (!bestE || d < bestE.d)) bestE = { p, d };
    }
  }
  return bestE ? { point: bestE.p, snap: "edge" } : { point: hit.clone(), snap: "surface" };
}

export function measure(a: THREE.Vector3, b: THREE.Vector3): Measurement {
  return {
    total_mm: a.distanceTo(b) * 1000,
    horizontal_mm: Math.hypot(b.x - a.x, b.z - a.z) * 1000,
    vertical_mm: Math.abs(b.y - a.y) * 1000,
  };
}
