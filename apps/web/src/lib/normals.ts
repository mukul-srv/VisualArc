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

const UV_AXES = [[2, 1], [0, 2], [0, 1]] as const; // same box projection as the engine's box_uv: X-facing -> (z, y), Y -> (x, z), Z -> (x, y)

/** Give meshes UVs when the GLB has none (exported before textures existed): box projection in metres,
 *  mirroring the engine, so library textures show a pattern instead of one flat texel. Un-indexes the
 *  geometry (UVs differ per face). Returns how many meshes were fixed. */
export function ensureUVs(root: THREE.Object3D): number {
  let fixed = 0;
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh || m.geometry.getAttribute("uv")) return;
    const old = m.geometry;
    const g = old.index ? old.toNonIndexed() : old;
    const p = g.getAttribute("position");
    const uv = new Float32Array(p.count * 2);
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3();
    const pt = [a, b, c];
    for (let f = 0; f + 2 < p.count; f += 3) {
      a.fromBufferAttribute(p, f);
      b.fromBufferAttribute(p, f + 1);
      c.fromBufferAttribute(p, f + 2);
      n.subVectors(c, b).cross(new THREE.Vector3().subVectors(a, b));
      const ax = Math.abs(n.x) >= Math.abs(n.y) && Math.abs(n.x) >= Math.abs(n.z) ? 0 : Math.abs(n.y) >= Math.abs(n.z) ? 1 : 2;
      const [u, v] = UV_AXES[ax];
      pt.forEach((q, i) => {
        const xyz = q.toArray();
        uv[(f + i) * 2] = xyz[u];
        uv[(f + i) * 2 + 1] = xyz[v];
      });
    }
    g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    if (g !== old) {
      m.geometry = g;
      old.dispose();
    }
    fixed++;
  });
  return fixed;
}
