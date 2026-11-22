"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { getProject, glbUrl, isGenerationId } from "@/lib/api";
import { parseManifest, pickFloor, sortFloors, viewerUrl, type Floor, type Manifest } from "@/lib/project";
import { resolveStem } from "@/lib/model-stem";
import { ViewerNav } from "@/components/ViewerNav";
import { MetadataPanel } from "@/components/MetadataPanel";
import { orbitLimits, planFrustum } from "@/lib/camera";
import { openingBox, pickElement } from "@/lib/pick";
import { CEILING_LAYER, collectColliders, layerCeilings, makeDoubleSided, modelBox, moveWithCollision, spawnPoint, WALK } from "@/lib/walk";
import { measure, snapPoint, type Measurement, type SnapKind } from "@/lib/measure";
import { describeElement, describeOpening, PROVENANCE_LABEL, type ElementData, type OpeningData, type Panel } from "@/lib/selection";

// Viewer only renders. GLB is already metres, Y-up (ADR-001); no unit/axis fixes here.

export default function ViewerPage() {
  const mount = useRef<HTMLDivElement>(null);
  const setTop = useRef<(top: boolean) => void>(() => {});
  const toggleWalk = useRef<() => void>(() => {});
  const [walking, setWalking] = useState(false);
  const [top, setTopState] = useState(false);
  const [status, setStatus] = useState("loading…");
  const [panel, setPanel] = useState<Panel | null>(null);
  const toggleMeasure = useRef<() => void>(() => {});
  const [measuring, setMeasuring] = useState(false);
  const [result, setResult] = useState<{ m: Measurement; a: SnapKind; b: SnapKind } | null>(null);

  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [viewing, setViewing] = useState<number | null>(null); // past version number, read-only
  const [floorId, setFloorId] = useState<string | null>(null);
  const [target, setTarget] = useState<{ url: string; stem: string } | null>(null);
  const share = useRef<string | null>(null); // read-only link token
  const [shared, setShared] = useState<boolean | null>(null); // null until the URL is read; true: opened through a share link (no account pages)
  const floorTarget = (m: Manifest, f: Floor) => ({ url: glbUrl(f.generation_id, share.current), stem: `${m.name} / ${f.name}` });

  // Resolve what to load from the query string. The scene effect below reloads on `target`.
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    share.current = query.get("share");
    queueMicrotask(() => setShared(share.current !== null));
    // ?project=<id>[&floor=<id>] loads a project floor; ?generation=<id> one API model;
    // ?model=<stem> a local /models file
    const project = query.get("project");
    const generation = query.get("generation");
    if (project !== null) {
      if (!isGenerationId(project)) return queueMicrotask(() => setStatus("error: invalid project id"));
      const vq = query.get("version"); // read-only history view of an older version
      const version = vq === null ? undefined : Number(vq);
      if (version !== undefined && !(Number.isInteger(version) && version >= 1)) return queueMicrotask(() => setStatus("error: invalid version"));
      getProject(project, fetch, version, share.current).then((r) => {
        const m = r.ok ? parseManifest(r.manifest) : null;
        if (!r.ok || !m) return setStatus(r.ok ? "error: malformed project manifest" : `error: ${r.message}`);
        setViewing(version ?? null);
        const f = pickFloor(m, query.get("floor"));
        if (!f) return setStatus("error: project has no floors yet");
        setManifest(m);
        setFloorId(f.id);
        setTarget(floorTarget(m, f));
      });
    } else if (generation !== null) {
      if (!isGenerationId(generation)) return queueMicrotask(() => setStatus("error: invalid generation id"));
      queueMicrotask(() => setTarget({ url: glbUrl(generation), stem: `generation ${generation.slice(0, 8)}` }));
    } else {
      const name = resolveStem(query.get("model"));
      if (name === null) return queueMicrotask(() => setStatus("error: invalid model name (allowed: letters, digits, _ and -)"));
      queueMicrotask(() => setTarget({ url: `/models/${name}.glb`, stem: name }));
    }
  }, []);

  useEffect(() => {
    if (!target) return;
    const { url, stem } = target;
    const el = mount.current!;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1e1e22);
    const persp = new THREE.PerspectiveCamera(50, el.clientWidth / el.clientHeight, 0.1, 500);
    persp.position.set(10, 8, 10);
    const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 100);
    let camera: THREE.PerspectiveCamera | THREE.OrthographicCamera = persp;
    let planBox: THREE.Box3 | null = null;
    let saved3d: { position: THREE.Vector3; target: THREE.Vector3 } | null = null;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    const controls = new OrbitControls(persp as THREE.Camera, renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(5, 10, 5);
    scene.add(sun);
    let grid = new THREE.GridHelper(20, 20); // 1 cell = 1 m; resized to the model once loaded
    scene.add(grid);
    scene.add(new THREE.AxesHelper(2)); // R=X, G=Y(up), B=Z

    // --- selection: click (not drag) picks a mesh; a hit inside a wall's aperture picks the opening
    let model: THREE.Object3D | null = null;
    let selected: { mesh: THREE.Mesh; original: THREE.Material | THREE.Material[] } | null = null;
    let overlay: THREE.Mesh | null = null;
    const clearSelection = () => {
      if (selected) selected.mesh.material = selected.original;
      if (overlay) {
        scene.remove(overlay);
        overlay.geometry.dispose();
        (overlay.material as THREE.Material).dispose();
      }
      selected = null;
      overlay = null;
    };
    const showOpening = (o: OpeningData, thicknessMm: number, baseY: number) => {
      overlay = new THREE.Mesh(
        new THREE.BoxGeometry(1, 1, 1),
        new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.45 }),
      );
      const box = openingBox(o, thicknessMm, baseY);
      box.getCenter(overlay.position);
      box.getSize(overlay.scale);
      scene.add(overlay);
    };
    const raycaster = new THREE.Raycaster();
    let down: { x: number; y: number } | null = null;
    const canvas = renderer.domElement;
    // --- measure mode: click A, click B (snapped to vertex/edge), third click restarts
    let measureOn = false;
    let pts: { p: THREE.Vector3; snap: SnapKind }[] = [];
    let mObjs: THREE.Object3D[] = [];
    const clearMeasure = () => {
      mObjs.forEach((o) => {
        scene.remove(o);
        (o as THREE.Mesh).geometry.dispose();
        ((o as THREE.Mesh).material as THREE.Material).dispose();
      });
      mObjs = [];
      pts = [];
      setResult(null);
    };
    const setMeasure = (on: boolean) => {
      if (on && walk) return;
      measureOn = on;
      if (on) {
        clearSelection();
        setPanel(null);
      } else clearMeasure();
      setMeasuring(on);
    };
    toggleMeasure.current = () => setMeasure(!measureOn);
    const measureClick = (mesh: THREE.Mesh, hit: THREE.Vector3) => {
      if (pts.length === 2) clearMeasure();
      const s = snapPoint(hit, mesh, camera, { width: canvas.clientWidth, height: canvas.clientHeight }, 12);
      pts.push({ p: s.point, snap: s.snap });
      const mk = new THREE.Mesh(new THREE.SphereGeometry(0.05), new THREE.MeshBasicMaterial({ color: 0xff3366, depthTest: false }));
      mk.position.copy(s.point);
      mk.renderOrder = 1;
      scene.add(mk);
      mObjs.push(mk);
      if (pts.length < 2) return;
      const ln = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([pts[0].p, pts[1].p]),
        new THREE.LineBasicMaterial({ color: 0xff3366, depthTest: false }),
      );
      ln.renderOrder = 1;
      scene.add(ln);
      mObjs.push(ln);
      setResult({ m: measure(pts[0].p, pts[1].p), a: pts[0].snap, b: pts[1].snap });
    };
    const onDown = (e: PointerEvent) => (down = { x: e.clientX, y: e.clientY });
    const onUp = (e: PointerEvent) => {
      if (walk || !down || !model || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
      const r = canvas.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1),
        camera,
      );
      const pick = pickElement(model, raycaster.ray);
      if (measureOn) return pick && measureClick(pick.mesh, pick.point);
      clearSelection();
      if (!pick) return setPanel(null);
      const ud = pick.mesh.userData as ElementData;
      if (pick.opening) {
        // opening selected: overlay only, so the host wall is not shown as selected too
        showOpening(pick.opening, ud.thickness?.value ?? 0, pick.baseY);
        return setPanel(describeOpening(pick.opening));
      }
      const mat = (pick.mesh.material as THREE.MeshStandardMaterial).clone();
      mat.emissive.set(0xffaa00);
      mat.emissiveIntensity = 0.6;
      selected = { mesh: pick.mesh, original: pick.mesh.material };
      pick.mesh.material = mat;
      setPanel(describeElement(ud));
    };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointerup", onUp);

    // --- walk mode (T23): WASD/arrows move, drag looks around, Esc or the button exits
    const keys = new Set<string>();
    let walk: {
      pos: THREE.Vector3;
      floorY: number;
      yaw: number;
      pitch: number;
      colliders: THREE.Mesh[];
      restore: () => void;
      saved: { position: THREE.Vector3; target: THREE.Vector3 };
    } | null = null;
    let look: { x: number; y: number } | null = null;
    const aim = () => {
      if (!walk) return;
      camera.position.set(walk.pos.x, walk.floorY + WALK.eye, walk.pos.z);
      camera.lookAt(
        camera.position.x - Math.sin(walk.yaw) * Math.cos(walk.pitch),
        camera.position.y + Math.sin(walk.pitch),
        camera.position.z - Math.cos(walk.yaw) * Math.cos(walk.pitch),
      );
    };
    const exitWalk = () => {
      if (!walk) return;
      walk.restore();
      persp.layers.disable(CEILING_LAYER);
      keys.clear();
      camera.position.copy(walk.saved.position);
      controls.target.copy(walk.saved.target);
      controls.enabled = true;
      controls.update();
      walk = null;
      setWalking(false);
    };
    const enterWalk = () => {
      if (!model) return;
      if (camera === ortho) return setStatus("switch to Perspective to walk");
      const spawn = spawnPoint(model);
      if (!spawn) return setStatus("walk mode needs a floor boundary in the model");
      setMeasure(false);
      clearSelection();
      setPanel(null);
      const colliders = collectColliders(model);
      walk = {
        pos: spawn.pos,
        floorY: spawn.floorY,
        yaw: 0,
        pitch: 0,
        colliders,
        restore: makeDoubleSided(colliders),
        saved: { position: camera.position.clone(), target: controls.target.clone() },
      };
      persp.layers.enable(CEILING_LAYER); // ceilings are drawn only while walking
      controls.enabled = false;
      setWalking(true);
      aim();
    };
    toggleWalk.current = () => (walk ? exitWalk() : enterWalk());
    const onKey = (e: KeyboardEvent, down: boolean) => {
      if (e.key === "Escape" && down) return measureOn ? setMeasure(false) : exitWalk();
      if (down && walk) keys.add(e.key.toLowerCase());
      if (!down) keys.delete(e.key.toLowerCase()); // always, or a key released after Esc sticks
    };
    const onKeyDown = (e: KeyboardEvent) => onKey(e, true);
    const onKeyUp = (e: KeyboardEvent) => onKey(e, false);
    const onLookDown = (e: PointerEvent) => walk && (look = { x: e.clientX, y: e.clientY });
    const onLookMove = (e: PointerEvent) => {
      if (!walk || !look) return;
      walk.yaw -= (e.clientX - look.x) * 0.005;
      walk.pitch = Math.max(-1.2, Math.min(1.2, walk.pitch - (e.clientY - look.y) * 0.005));
      look = { x: e.clientX, y: e.clientY };
      aim();
    };
    const onLookUp = () => (look = null);
    const onBlur = () => keys.clear(); // focus lost while a key is held: no keyup arrives
    window.addEventListener("blur", onBlur);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    canvas.addEventListener("pointerdown", onLookDown);
    canvas.addEventListener("pointermove", onLookMove);
    window.addEventListener("pointerup", onLookUp);
    let last = performance.now();
    const stepWalk = () => {
      const now = performance.now();
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!walk) return;
      const f = (keys.has("w") || keys.has("arrowup") ? 1 : 0) - (keys.has("s") || keys.has("arrowdown") ? 1 : 0);
      const r = (keys.has("d") || keys.has("arrowright") ? 1 : 0) - (keys.has("a") || keys.has("arrowleft") ? 1 : 0);
      if (!f && !r) return;
      const fx = -Math.sin(walk.yaw);
      const fz = -Math.cos(walk.yaw);
      const d = new THREE.Vector2(fx * f - fz * r, fz * f + fx * r).normalize().multiplyScalar(WALK.speed * dt);
      moveWithCollision(walk.pos, d, walk.floorY, walk.colliders);
      aim();
    };

    let center = new THREE.Vector3();
    let size = 10;
    const fitPlan = () => {
      if (!planBox) return;
      const f = planFrustum(planBox, el.clientWidth / el.clientHeight, 0.1);
      Object.assign(ortho, { left: f.left, right: f.right, top: f.top, bottom: f.bottom, near: f.near, far: f.far });
      ortho.zoom = 1;
      ortho.position.copy(f.position);
      ortho.up.set(0, 0, -1); // plan up = -Z (plan Y -> -Z)
      controls.target.set(f.position.x, planBox.min.y, f.position.z);
      ortho.updateProjectionMatrix();
    };
    const place = (isTop: boolean) => {
      if (isTop && camera === persp && planBox) {
        saved3d = { position: persp.position.clone(), target: controls.target.clone() };
        camera = ortho;
        controls.object = ortho;
        controls.enableRotate = false;
        controls.mouseButtons.LEFT = THREE.MOUSE.PAN; // click-drag moves across the plan
        controls.touches.ONE = THREE.TOUCH.PAN;
        fitPlan();
      } else if (!isTop && camera === ortho && saved3d) {
        camera = persp;
        controls.object = persp;
        controls.enableRotate = true;
        controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
        controls.touches.ONE = THREE.TOUCH.ROTATE;
        persp.position.copy(saved3d.position);
        controls.target.copy(saved3d.target);
      } else if (!isTop) {
        const d = size * 1.5; // initial 3D framing
        controls.target.copy(center);
        persp.position.set(center.x + d, center.y + d * 0.7, center.z + d);
      }
      controls.update();
    };
    setTop.current = place;

    new GLTFLoader().load(
      url,
      (gltf) => {
        scene.add(gltf.scene);
        model = gltf.scene;
        layerCeilings(model);
        const box = modelBox(model);
        const s = box.getSize(new THREE.Vector3());
        center = box.getCenter(new THREE.Vector3());
        size = Math.max(s.x, s.z);
        planBox = box;
        // grid extends well past the model (3x its larger side, min 20 m, even cell count)
        const cells = Math.max(20, Math.ceil((size * 3) / 2) * 2);
        scene.remove(grid);
        grid.dispose();
        grid = new THREE.GridHelper(cells, cells);
        grid.position.set(center.x, box.min.y, center.z);
        scene.add(grid);
        Object.assign(controls, orbitLimits(box));
        place(false);
        setStatus(`${stem}: ${s.x.toFixed(2)} × ${s.z.toFixed(2)} × ${s.y.toFixed(2)} m (X × Z × H)`);
      },
      undefined,
      () => setStatus(`error: could not load ${url} (missing, unreachable or not a valid GLB). For API models check the backend is running; for ?model= build it and copy it to apps/web/public/models/`),
    );

    renderer.setAnimationLoop(() => {
      stepWalk();
      renderer.render(scene, camera);
    });
    const onResize = () => {
      persp.aspect = el.clientWidth / el.clientHeight;
      persp.updateProjectionMatrix();
      if (camera === ortho) fitPlan();
      renderer.setSize(el.clientWidth, el.clientHeight);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      canvas.removeEventListener("pointerdown", onLookDown);
      canvas.removeEventListener("pointermove", onLookMove);
      window.removeEventListener("pointerup", onLookUp);
      exitWalk();
      clearSelection();
      clearMeasure();
      model?.traverse((o) => {
        // free the previous floor's GPU memory when switching
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        [m.material].flat().forEach((x) => x?.dispose());
      });
      renderer.setAnimationLoop(null);
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [target]);

  const floors = manifest ? sortFloors(manifest.floors) : [];
  const current = floors.find((f) => f.id === floorId);
  const selectFloor = (f: Floor) => {
    if (!manifest || f.id === floorId) return;
    setPanel(null);
    setTopState(false);
    setFloorId(f.id);
    setTarget(floorTarget(manifest, f));
    window.history.replaceState(null, "", viewerUrl(manifest.id, f.id, viewing ?? undefined, share.current));
  };

  return (
    <div style={{ position: "fixed", inset: 0 }}>
      <div ref={mount} style={{ width: "100%", height: "100%" }} />
      <div style={{ position: "absolute", top: 12, left: 12, color: "#eee", font: "14px monospace" }}>
        <button
          disabled={walking}
          onClick={() => {
            setTopState(!top);
            setTop.current(!top);
          }}
        >
          {top ? "Perspective" : "Top-down"}
        </button>{" "}
        <button onClick={() => toggleWalk.current()}>{walking ? "Exit walk (Esc)" : "Walk"}</button>{" "}
        <button disabled={walking} onClick={() => toggleMeasure.current()}>
          {measuring ? "Measure: on (Esc)" : "Measure"}
        </button>{" "}
        {walking ? "WASD/arrows move, drag to look" : status}
        <ViewerNav shared={shared} manifest={manifest} viewing={viewing} />
        {floors.length > 0 && (
          <div role="group" aria-label="Floors" style={{ marginTop: 6 }}>
            {floors.map((f) => (
              <div key={f.id}>
                <button disabled={walking} aria-pressed={f.id === floorId} onClick={() => selectFloor(f)}>
                  {f.id === floorId ? "▶ " : ""}
                  {f.name}: {Number(f.elevation.value.toFixed(3))} mm [{PROVENANCE_LABEL[f.elevation.source]}]
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
      <div
        style={{
          position: "absolute",
          top: 12,
          right: 12,
          maxWidth: 380,
          padding: 10,
          background: "rgba(20,20,24,0.9)",
          color: "#eee",
          font: "13px monospace",
        }}
      >
        {current && (
          <div style={{ marginBottom: 8 }}>
            <b>{current.name}</b> <code>{current.id}</code>: elevation {Number(current.elevation.value.toFixed(3))} mm [
            {PROVENANCE_LABEL[current.elevation.source]}]
          </div>
        )}
        <MetadataPanel panel={panel} />
        {measuring && (
          <div>
            <b>Viewer measurement (not source data)</b>
            {result ? (
              <div>
                total {result.m.total_mm.toFixed(1)} mm
                <br />
                horizontal {result.m.horizontal_mm.toFixed(1)} mm, vertical {result.m.vertical_mm.toFixed(1)} mm
                <br />
                snap: A {result.a}, B {result.b}
              </div>
            ) : (
              <div>click point A, then point B</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
