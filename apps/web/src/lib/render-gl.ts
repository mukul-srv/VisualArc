import * as THREE from "three";
import { SKY_LIGHT } from "./lighting";
import { runTrace, browserSchedule, type TraceStatus } from "./pathtrace";
import { MAX_TRIANGLES, type TraceSettings } from "./render-settings";

// WebGL side of the render panel: the path-traced still (three-gpu-pathtracer's WebGLPathTracer on its own
// offscreen renderer, loaded on demand) and helpers for the realtime screenshot. Not unit-tested (no WebGL
// in the test environment); the settings and stop logic it uses are (render-settings, pathtrace).

/** Largest drawing buffer edge (px) this GPU allows. */
export function maxRenderDim(renderer: THREE.WebGLRenderer): number {
  const gl = renderer.getContext();
  const vp = gl.getParameter(gl.MAX_VIEWPORT_DIMS) as Int32Array | number[];
  return Math.min(renderer.capabilities.maxTextureSize, gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) as number, vp[0], vp[1]);
}

/** Triangles of the meshes that would be traced (visible ones). */
export function triangleCount(root: THREE.Object3D): number {
  let n = 0;
  root.traverseVisible((o) => {
    const m = o as THREE.Mesh;
    if (m.isMesh) n += (m.geometry.index?.count ?? m.geometry.attributes.position.count) / 3;
  });
  return n;
}

/** Change a camera's aspect (output size differs from the viewport): perspective keeps its vertical fov,
 *  orthographic keeps its height. Returns a function that puts the camera back. */
export function setAspect(camera: THREE.Camera, aspect: number): () => void {
  if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
    const c = camera as THREE.PerspectiveCamera;
    const old = c.aspect;
    c.aspect = aspect;
    c.updateProjectionMatrix();
    return () => {
      c.aspect = old;
      c.updateProjectionMatrix();
    };
  }
  const c = camera as THREE.OrthographicCamera;
  const old = { l: c.left, r: c.right };
  const half = (c.top - c.bottom) / 2;
  const mid = (c.left + c.right) / 2;
  c.left = mid - half * aspect;
  c.right = mid + half * aspect;
  c.updateProjectionMatrix();
  return () => {
    c.left = old.l;
    c.right = old.r;
    c.updateProjectionMatrix();
  };
}

export type StillArgs = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera | THREE.OrthographicCamera;
  settings: TraceSettings;
  size: { w: number; h: number };
  accuracy: boolean; // flat look: no tone mapping curve
  skyStrength: number; // 0..1 from the sun's elevation
  hide: THREE.Object3D[]; // helpers and lights the tracer must not see (grid, axes, hemisphere, fill)
  onStatus: (s: TraceStatus) => void;
};
export type Still = {
  canvas: HTMLCanvasElement;
  done: Promise<"samples" | "time" | "user">;
  stop: () => void;
  /** PNG of what has been traced so far (call before dispose). */
  png: () => Promise<Blob | null>;
  /** Free every GPU resource and put the live scene back as it was. Safe to call twice. */
  dispose: () => void;
};

/** Build the path tracer for the current scene and start sampling. Rejects with a readable Error when it
 *  cannot (too big, no float render targets, shader or BVH failure); everything it made is freed first. */
export async function beginStill(a: StillArgs): Promise<Still> {
  const tris = triangleCount(a.scene);
  if (tris > MAX_TRIANGLES) throw new Error(`The model has ${Math.round(tris).toLocaleString()} triangles, more than the ${MAX_TRIANGLES.toLocaleString()} the path tracer is allowed to build. Isolate a floor and try again.`);
  const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
  const saved = { background: a.scene.background, environment: a.scene.environment, intensity: a.scene.environmentIntensity, hidden: a.hide.map((o) => o.visible) };
  let tracer: { dispose(): void } | null = null;
  let sky: { dispose(): void } | null = null;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    a.scene.background = saved.background;
    a.scene.environment = saved.environment;
    a.scene.environmentIntensity = saved.intensity;
    a.hide.forEach((o, i) => (o.visible = saved.hidden[i]));
    try {
      tracer?.dispose();
      sky?.dispose();
    } finally {
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    }
  };
  try {
    if (!renderer.extensions.has("EXT_color_buffer_float")) throw new Error("This browser or GPU cannot render to float textures (EXT_color_buffer_float), which the path tracer needs. The realtime screenshot still works.");
    renderer.setPixelRatio(1);
    renderer.setSize(a.size.w, a.size.h, false);
    renderer.domElement.style.cssText = "max-width:100%;max-height:50vh;display:block";
    renderer.toneMapping = a.accuracy ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping;
    const { WebGLPathTracer, GradientEquirectTexture } = await import("three-gpu-pathtracer");
    const gradient = new GradientEquirectTexture();
    gradient.topColor.set(SKY_LIGHT.sky);
    gradient.bottomColor.set(SKY_LIGHT.ground);
    gradient.update();
    sky = gradient;
    // the viewer's PMREM reflections belong to the viewer's GL context: trace against a plain sky instead
    a.scene.background = gradient;
    a.scene.environment = gradient;
    a.scene.environmentIntensity = a.skyStrength;
    a.hide.forEach((o) => (o.visible = false));
    const cam = a.camera.clone() as typeof a.camera; // the viewer's own camera is left alone
    cam.updateMatrixWorld(true);
    setAspect(cam, a.size.w / a.size.h);
    const pt = new WebGLPathTracer(renderer);
    tracer = pt;
    await new Promise((r) => setTimeout(r, 30)); // let the panel paint "building" before the synchronous BVH build
    Object.assign(pt, { renderDelay: 0, minSamples: 1, fadeDuration: 0, rasterizeScene: false, dynamicLowRes: false });
    const side = Math.max(a.size.w, a.size.h);
    pt.tiles.set(side > 2500 ? 3 : side > 1200 ? 2 : 1, side > 2500 ? 3 : side > 1200 ? 2 : 1);
    pt.setScene(a.scene, cam);
    const run = runTrace(pt, a.settings, browserSchedule, a.onStatus);
    return {
      canvas: renderer.domElement,
      done: run.done,
      stop: run.stop,
      png: () => new Promise((res) => renderer.domElement.toBlob(res, "image/png")),
      dispose,
    };
  } catch (e) {
    dispose();
    throw e;
  }
}
