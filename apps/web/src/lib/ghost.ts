import * as THREE from "three";

export const GHOST_OPACITY = 0.12;

/** Draw a floor model faintly (or restore it): isolate mode can show the other floors as ghosts. The
 *  original look is kept on each material so switching back is exact. A ghost is not pickable. */
export function setGhost(root: THREE.Object3D, on: boolean): void {
  root.userData.ghost = on;
  root.traverse((o) => {
    if (!(o as THREE.Mesh).isMesh) return;
    for (const m of [(o as THREE.Mesh).material].flat()) {
      m.userData.orig ??= { transparent: m.transparent, opacity: m.opacity, depthWrite: m.depthWrite };
      const t = on ? { transparent: true, opacity: GHOST_OPACITY, depthWrite: false } : m.userData.orig;
      Object.assign(m, t);
      m.needsUpdate = true;
    }
  });
}
