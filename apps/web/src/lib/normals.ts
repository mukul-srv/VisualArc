import * as THREE from "three";

/** Give every mesh vertex normals. GLBs exported before the engine wrote NORMAL have none; three then
 *  flat-shades the plain material, but normal-pass effects (GTAO) and the shadow normal bias read the
 *  missing attribute and go black. The geometry is un-indexed first so no normal is smoothed across an
 *  edge (flat faces stay flat). Returns how many meshes were fixed. */
export function ensureNormals(root: THREE.Object3D): number {
  let fixed = 0;
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh || m.geometry.getAttribute("normal")) return;
    const old = m.geometry;
    const g = old.index ? old.toNonIndexed() : old;
    g.computeVertexNormals();
    if (g !== old) {
      m.geometry = g;
      old.dispose();
    }
    fixed++;
  });
  return fixed;
}
