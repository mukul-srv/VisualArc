import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { GTAOPass } from "three/examples/jsm/postprocessing/GTAOPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { SKY_LIGHT, SUN_LIGHT } from "./lighting";
import { setAspect } from "./render-gl";
import { shadowFrustum, type Quality } from "./quality";
import type { ArtificialLight } from "./site-lighting";

// The viewer's light and render setup in one place: sky + sun (with a shadow frustum fitted to the
// building), procedural room reflections, GTAO ambient occlusion and the user's artificial lights.
// Everything heavy is switched by a Quality preset and released in dispose().
export const LIGHT_UNIT = 8; // three.js intensity per unit of the user's intensity slider (decay 2, metres)
export const MAX_SHADOW_POINT_LIGHTS = 4;

export type RigInput = {
  quality: Quality;
  sunDir: [number, number, number] | null; // null: the default fixed sun
  sunStrength: number; // multiplies the default sun intensity
  skyStrength: number; // multiplies the default sky intensity
  lights: ArtificialLight[];
  selectedLight: string | null;
};

export function createRig(scene: THREE.Scene, renderer: THREE.WebGLRenderer) {
  const hemi = new THREE.HemisphereLight(SKY_LIGHT.sky, SKY_LIGHT.ground, SKY_LIGHT.intensity);
  const sun = new THREE.DirectionalLight(SUN_LIGHT.color, SUN_LIGHT.intensity);
  sun.shadow.bias = -0.0005;
  sun.shadow.normalBias = 0.03;
  scene.add(hemi, sun, sun.target);
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  let dir = new THREE.Vector3(...SUN_LIGHT.dir).normalize();
  let frustum = { centre: new THREE.Vector3(), radius: 10 };
  let env: THREE.Texture | null = null;
  let pmrem: THREE.PMREMGenerator | null = null;
  let composer: EffectComposer | null = null;
  let q: Quality | null = null;
  let size = { w: 1, h: 1 };
  let built: THREE.Object3D[] = [];
  let ssaoFailed = false;

  const place = () => {
    sun.position.copy(frustum.centre).addScaledVector(dir, frustum.radius * 1.5);
    sun.target.position.copy(frustum.centre);
    const c = sun.shadow.camera;
    const r = frustum.radius;
    Object.assign(c, { left: -r, right: r, top: r, bottom: -r, near: 0.1, far: r * 3.2 });
    c.updateProjectionMatrix();
  };

  const dropLights = () => {
    built.forEach((o) => {
      o.parent?.remove(o);
      o.traverse((c) => {
        const m = c as THREE.Mesh;
        m.geometry?.dispose();
        (m.material as THREE.Material | undefined)?.dispose();
        (c as THREE.SpotLight).shadow?.map?.dispose();
      });
    });
    built = [];
  };

  const setComposer = (on: boolean) => {
    if (!on && composer) {
      composer.dispose();
      composer = null;
    }
  };

  const resize = (w: number, h: number) => {
    size = { w, h };
    renderer.setSize(w, h);
    composer?.setPixelRatio(renderer.getPixelRatio());
    composer?.setSize(w, h);
  };

  const render = (scene3: THREE.Scene, camera: THREE.Camera, persp: THREE.Camera) => {
    if (q?.ssao && camera === persp && !ssaoFailed) {
      try {
        if (!composer) {
          composer = new EffectComposer(renderer);
          composer.setPixelRatio(renderer.getPixelRatio());
          composer.setSize(size.w, size.h);
          composer.addPass(new RenderPass(scene3, camera));
          composer.addPass(new GTAOPass(scene3, camera, size.w, size.h));
          composer.addPass(new OutputPass());
        }
        composer.render();
        return;
      } catch {
        ssaoFailed = true; // never take the viewer down for an effect: fall back to the plain render
        setComposer(false);
      }
    }
    renderer.render(scene3, camera);
  };

  /** PNG of the current view at w x h px (the viewer is resized for one synchronous frame and put back). */
  const capture = (scene3: THREE.Scene, camera: THREE.Camera, persp: THREE.Camera, w: number, h: number): Promise<Blob | null> => {
    const ratio = renderer.getPixelRatio();
    const was = size;
    renderer.setPixelRatio(1);
    resize(w, h);
    const undo = setAspect(camera, w / h);
    try {
      render(scene3, camera, persp);
      return new Promise((res) => renderer.domElement.toBlob(res, "image/png")); // the bitmap is taken now
    } finally {
      undo();
      renderer.setPixelRatio(ratio);
      resize(was.w, was.h);
    }
  };

  return {
    capture,
    resize,
    render,
    sun,
    hemi,
    /** Shadows follow the building: a frustum around its bounds, valid from any sun angle. */
    fit(box: THREE.Box3) {
      if (box.isEmpty()) return;
      const f = shadowFrustum(box.min.toArray(), box.max.toArray());
      frustum = { centre: new THREE.Vector3(...f.centre), radius: f.radius };
      place();
    },
    /** Meshes cast and receive shadows (glass casts none: it would black out the room behind it). */
    prepare(root: THREE.Object3D) {
      root.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        m.castShadow = !(m.userData?.type === "opening_part" && m.userData?.part === "glass");
        m.receiveShadow = true;
      });
    },
    update(input: RigInput, roots: { rootOf: (floorId: string) => THREE.Object3D | undefined; elevationMm: (floorId: string) => number }) {
      const next = input.quality;
      const shadowsChanged = !q || (q.shadowMap > 0) !== (next.shadowMap > 0);
      if (!q || q.shadowMap !== next.shadowMap) {
        renderer.shadowMap.enabled = next.shadowMap > 0;
        sun.castShadow = next.shadowMap > 0;
        sun.shadow.map?.dispose();
        sun.shadow.map = null;
        sun.shadow.mapSize.set(next.shadowMap || 1, next.shadowMap || 1);
      }
      if (shadowsChanged) scene.traverse((o) => [(o as THREE.Mesh).material].flat().forEach((m) => m && (m.needsUpdate = true)));
      if (next.env && !env) {
        pmrem = new THREE.PMREMGenerator(renderer);
        env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      }
      scene.environment = next.env ? env : null;
      scene.environmentIntensity = 0.35;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, next.pixelRatioMax));
      resize(size.w, size.h); // the drawing buffer follows the pixel ratio
      if (!next.ssao) setComposer(false);
      q = next;

      dir = input.sunDir ? new THREE.Vector3(...input.sunDir).normalize() : new THREE.Vector3(...SUN_LIGHT.dir).normalize();
      place();
      sun.intensity = SUN_LIGHT.intensity * input.sunStrength;
      hemi.intensity = SKY_LIGHT.intensity * input.skyStrength;

      dropLights();
      if (!next.artificial) return;
      input.lights.forEach((l, i) => {
        const root = roots.rootOf(l.floor_id);
        if (!root) return; // its floor is gone or not loaded: nothing to light
        const g = new THREE.Group();
        g.position.set(l.x_mm / 1000, (roots.elevationMm(l.floor_id) + l.height_mm) / 1000, -l.y_mm / 1000);
        const color = new THREE.Color(l.color);
        const light = l.kind === "spot" ? new THREE.SpotLight(color, l.intensity * LIGHT_UNIT, 0, Math.PI / 3, 0.5, 2) : new THREE.PointLight(color, l.intensity * LIGHT_UNIT, 0, 2);
        if (light instanceof THREE.SpotLight) {
          light.target.position.set(0, -1, 0);
          g.add(light.target);
        }
        light.castShadow = next.shadowMap >= 2048 && i < MAX_SHADOW_POINT_LIGHTS;
        light.shadow.mapSize.set(512, 512);
        g.add(light);
        const gizmo = new THREE.Mesh(new THREE.SphereGeometry(l.id === input.selectedLight ? 0.14 : 0.08), new THREE.MeshBasicMaterial({ color }));
        gizmo.userData = { gizmo: l.id };
        g.add(gizmo);
        root.add(g);
        built.push(g);
      });
    },
    /** SSAO needs the perspective camera the passes were built for; the plan (ortho) view renders directly. */
    dispose() {
      dropLights();
      setComposer(false);
      env?.dispose();
      pmrem?.dispose();
      sun.shadow.map?.dispose();
      scene.remove(hemi, sun, sun.target);
    },
  };
}
export type Rig = ReturnType<typeof createRig>;
