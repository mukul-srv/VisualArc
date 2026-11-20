"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { glbUrl, isGenerationId } from "@/lib/api";
import { resolveStem } from "@/lib/model-stem";

// Viewer only renders. GLB is already metres, Y-up (ADR-001); no unit/axis fixes here.

export default function ViewerPage() {
  const mount = useRef<HTMLDivElement>(null);
  const setTop = useRef<(top: boolean) => void>(() => {});
  const [top, setTopState] = useState(false);
  const [status, setStatus] = useState("loading…");

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
    </div>
  );
}
