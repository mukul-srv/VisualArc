"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { glbUrl, isGenerationId } from "@/lib/api";
import { resolveStem } from "@/lib/model-stem";
import { MetadataPanel } from "@/components/MetadataPanel";
import { openingBox, pickElement } from "@/lib/pick";
import { describeElement, describeOpening, type ElementData, type OpeningData, type Panel } from "@/lib/selection";

// Viewer only renders. GLB is already metres, Y-up (ADR-001); no unit/axis fixes here.

export default function ViewerPage() {
  const mount = useRef<HTMLDivElement>(null);
  const setTop = useRef<(top: boolean) => void>(() => {});
  const [top, setTopState] = useState(false);
  const [status, setStatus] = useState("loading…");
  const [panel, setPanel] = useState<Panel | null>(null);

  useEffect(() => {
    const el = mount.current!;
    const query = new URLSearchParams(window.location.search);
    // ?generation=<id> loads an API-generated model; ?model=<stem> a local /models file
    const generation = query.get("generation");
    let stem: string | null = null;
    let url: string;
    if (generation !== null) {
      if (!isGenerationId(generation)) {
        queueMicrotask(() => setStatus("error: invalid generation id"));
        return;
      }
      stem = `generation ${generation.slice(0, 8)}`;
      url = glbUrl(generation);
    } else {
      const name = resolveStem(query.get("model"));
      if (name === null) {
        queueMicrotask(() => setStatus("error: invalid model name (allowed: letters, digits, _ and -)"));
        return;
      }
      stem = name;
      url = `/models/${name}.glb`;
    }
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1e1e22);
    const camera = new THREE.PerspectiveCamera(50, el.clientWidth / el.clientHeight, 0.1, 500);
    camera.position.set(10, 8, 10);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(5, 10, 5);
    scene.add(sun);
    scene.add(new THREE.GridHelper(20, 20)); // 1 cell = 1 m
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
    const onDown = (e: PointerEvent) => (down = { x: e.clientX, y: e.clientY });
    const onUp = (e: PointerEvent) => {
      if (!down || !model || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
      const r = canvas.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1),
        camera,
      );
      clearSelection();
      const pick = pickElement(model, raycaster.ray);
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

    let center = new THREE.Vector3();
    let size = 10;
    const place = (isTop: boolean) => {
      const d = size * 1.5;
      controls.target.copy(center);
      if (isTop) camera.position.set(center.x, center.y + d * 1.5, center.z + 0.001);
      else camera.position.set(center.x + d, center.y + d * 0.7, center.z + d);
      controls.update();
    };
    setTop.current = place;

    new GLTFLoader().load(
      url,
      (gltf) => {
        scene.add(gltf.scene);
        model = gltf.scene;
        const box = new THREE.Box3().setFromObject(gltf.scene);
        const s = box.getSize(new THREE.Vector3());
        center = box.getCenter(new THREE.Vector3());
        size = Math.max(s.x, s.z);
        place(false);
        setStatus(`${stem}: ${s.x.toFixed(2)} × ${s.z.toFixed(2)} × ${s.y.toFixed(2)} m (X × Z × H)`);
      },
      undefined,
      () => setStatus(`error: could not load ${url} (missing, unreachable or not a valid GLB). For API models check the backend is running; for ?model= build it and copy it to apps/web/public/models/`),
    );

    renderer.setAnimationLoop(() => renderer.render(scene, camera));
    const onResize = () => {
      camera.aspect = el.clientWidth / el.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(el.clientWidth, el.clientHeight);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      clearSelection();
      renderer.setAnimationLoop(null);
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  return (
    <div style={{ position: "fixed", inset: 0 }}>
      <div ref={mount} style={{ width: "100%", height: "100%" }} />
      <div style={{ position: "absolute", top: 12, left: 12, color: "#eee", font: "14px monospace" }}>
        <button
          onClick={() => {
            setTopState(!top);
            setTop.current(!top);
          }}
        >
          {top ? "Perspective" : "Top-down"}
        </button>{" "}
        {status}
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
        <MetadataPanel panel={panel} />
      </div>
    </div>
  );
}
