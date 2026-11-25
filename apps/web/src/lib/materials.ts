import * as THREE from "three";
import index from "../../public/materials/index.json";
import { API_BASE, send } from "./api";

// Material library (CC0 PBR sets in public/materials) and its per-element use. The project stores
// "<floor id>/<element id>" -> library id (server validates the ids); no entry = the default flat colour.
export type MaterialDef = { id: string; label: string; tile_m: number; suits: string[]; metalness?: number };
export type MaterialMap = Record<string, string>;
export const LIBRARY: MaterialDef[] = index;

export const materialKey = (floorId: string, elementId: string) => `${floorId}/${elementId}`;
export const libraryFor = (type: string) => LIBRARY.filter((m) => m.suits.includes(type));
export const labelOf = (id: string) => LIBRARY.find((m) => m.id === id)?.label ?? id;

/** Keep only string -> known library id entries (untrusted manifest). */
export function parseMaterials(x: unknown): MaterialMap {
  const out: MaterialMap = {};
  if (x && typeof x === "object")
    for (const [k, v] of Object.entries(x)) if (typeof v === "string" && LIBRARY.some((m) => m.id === v)) out[k] = v;
  return out;
}

type Maps = { map: THREE.Texture; normalMap: THREE.Texture; roughnessMap: THREE.Texture };
export type TextureCache = { get: (def: MaterialDef) => Maps; dispose: () => void };

/** One set of textures per library id, loaded once. UVs are metres (engine box projection), so the
 *  repeat is 1 / tile size. `load` is injectable for tests. */
export function textureCache(load: (url: string) => THREE.Texture = (u) => new THREE.TextureLoader().load(u)): TextureCache {
  const sets = new Map<string, Maps>();
  const tex = (def: MaterialDef, name: string, srgb: boolean) => {
    const t = load(`/materials/${def.id}/${name}.jpg`);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(1 / def.tile_m, 1 / def.tile_m);
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    return t;
  };
  return {
    get: (def) => {
      let s = sets.get(def.id);
      if (!s) sets.set(def.id, (s = { map: tex(def, "color", true), normalMap: tex(def, "normal", false), roughnessMap: tex(def, "roughness", false) }));
      return s;
    },
    dispose: () => {
      sets.forEach((s) => Object.values(s).forEach((t) => t.dispose()));
      sets.clear();
    },
  };
}

/** Apply the chosen library materials to a floor's meshes (one material per mesh, so ghosting and
 *  selection never leak to another mesh); a mesh with no choice gets its original GLB material back. */
export function applyMaterials(root: THREE.Object3D, floorId: string | null, map: MaterialMap, cache: TextureCache): void {
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    const id = mesh.userData?.id as string | undefined;
    if (!mesh.isMesh || !id || floorId === null) return;
    const def = LIBRARY.find((m) => m.id === map[materialKey(floorId, id)]);
    const applied = mesh.userData.appliedMaterial as THREE.Material | undefined;
    if (!def) {
      if (!applied) return;
      mesh.material = mesh.userData.originalMaterial;
      applied.dispose();
      delete mesh.userData.appliedMaterial;
      return;
    }
    if (applied?.userData.libraryId === def.id) return;
    mesh.userData.originalMaterial ??= mesh.material;
    const mat = new THREE.MeshStandardMaterial({ ...cache.get(def), roughness: 1, metalness: def.metalness ?? 0 });
    mat.userData.libraryId = def.id;
    mesh.material = mat;
    mesh.userData.appliedMaterial = mat;
    applied?.dispose();
  });
}

export const putMaterials = (pid: string, materials: MaterialMap, f: typeof fetch = fetch) =>
  send<{ materials: MaterialMap; version: number }>(() =>
    f(`${API_BASE}/api/v1/projects/${pid}/materials`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ materials }),
    }),
  );
