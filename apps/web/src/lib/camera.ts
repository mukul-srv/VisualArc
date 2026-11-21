import * as THREE from "three";

// Pure camera math for the viewer (no DOM, no renderer).

/** Orthographic frustum + position for a straight-down plan view fitted to `box`. */
export function planFrustum(box: THREE.Box3, aspect: number, margin = 0.1) {
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  // Fit both plan extents (X, Z) inside the viewport aspect, then add margin.
  const halfH = (Math.max(s.z, s.x / aspect) / 2) * (1 + margin);
  const halfW = halfH * aspect;
  return {
    left: -halfW,
    right: halfW,
    top: halfH,
    bottom: -halfH,
    near: 0.1,
    far: s.y + 10, // camera sits 5 m above the top; far reaches 5 m below the floor
    position: new THREE.Vector3(c.x, box.max.y + 5, c.z),
  };
}

/** Orbit limits for the 3D camera, derived from the model's bounding-box diagonal. */
export function orbitLimits(box: THREE.Box3) {
  const diag = box.getSize(new THREE.Vector3()).length();
  return {
    minDistance: diag * 0.05,
    maxDistance: diag * 4,
    maxPolarAngle: Math.PI / 2 - 0.02, // never below the ground plane
  };
}
