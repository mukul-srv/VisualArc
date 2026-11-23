"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { canonicalUrl, getProject, glbUrl, isGenerationId } from "@/lib/api";
import { getBuilding, type Building } from "@/lib/building";
import { blockedHint, blockedStairAt, blockedStairs, floorAtHeight, floorState, GAP, manifestBuilding, placements, walkableFloors, type View } from "@/lib/building-view";
import { setGhost } from "@/lib/ghost";
import { BuildingControls, BuildingStats } from "@/components/BuildingControls";
import { parseManifest, pickFloor, sortFloors, viewerUrl, type Floor, type Manifest } from "@/lib/project";
import { resolveStem } from "@/lib/model-stem";
import { ViewerNav } from "@/components/ViewerNav";
import { MetadataPanel } from "@/components/MetadataPanel";
import { RoomList } from "@/components/RoomList";
import { ViewerToolbar } from "@/components/ViewerToolbar";
import { orbitLimits, planFrustum } from "@/lib/camera";
import { openingBox, pickElement } from "@/lib/pick";
import { animate as animateDoors, blocking, buildDoors, canClose, DOOR, distanceToOpening, doorFor, nearestDoor, toggle as toggleDoor, whyNoToggle, type Door } from "@/lib/doors";
import { collectSupports, dampTo, fall, groundLevel, stepOnto, stepUpLimit } from "@/lib/ground";
import { applyCeilingVisibility, hasRoof, setRoofVisible } from "@/lib/roof";
import { createTapGate } from "@/lib/tap";
import { setWalkFill, SKY_LIGHT, SUN_LIGHT, WALK_FILL } from "@/lib/lighting";
import { CEILING_LAYER, collectColliders, layerCeilings, makeDoubleSided, modelBox, moveWithCollision, spawnPoint, WALK } from "@/lib/walk";
import { measure, snapPoint, type Measurement, type SnapKind } from "@/lib/measure";
import { describeElement, describeOpening, describeRoom, PROVENANCE_LABEL, type ElementData, type OpeningData, type Panel, type RoomData } from "@/lib/selection";

// Viewer only renders. GLB is already metres, Y-up (ADR-001); no unit/axis fixes here.

export default function ViewerPage() {
  const mount = useRef<HTMLDivElement>(null);
  const setTop = useRef<(top: boolean) => void>(() => {});
  const toggleWalk = useRef<() => void>(() => {});
  const [walking, setWalking] = useState(false);
  const [top, setTopState] = useState(false);
  const [status, setStatus] = useState("loading…");
  const [panel, setPanel] = useState<Panel | null>(null);
  const [rooms, setRooms] = useState<RoomData[]>([]);
  const [roofPresent, setRoofPresent] = useState(false);
  const [roofOn, setRoofOn] = useState(true);
  const setRoof = useRef<(on: boolean) => void>(() => {});
  const [hint, setHint] = useState<string | null>(null); // a short message, e.g. why a door does not open
  const lowestMm = useRef<number | null>(null); // lowest floor of the project: the grid sits there
  const toggleMeasure = useRef<() => void>(() => {});
  const [measuring, setMeasuring] = useState(false);
  const [result, setResult] = useState<{ m: Measurement; a: SnapKind; b: SnapKind } | null>(null);

  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [viewing, setViewing] = useState<number | null>(null); // past version number, read-only
  // what to load: every floor's GLB of a project (id = floor id), or one model (id null)
  const [target, setTarget] = useState<{ stem: string; loads: { id: string | null; url: string }[] } | null>(null);
  const [building, setBuilding] = useState<Building | null>(null); // floors with offsets and stair pairings
  const [view, setView] = useState<View>({ mode: "whole", activeId: null, gap: GAP.default, ghost: false });
  const viewRef = useRef(view);
  const buildingRef = useRef<Building | null>(null);
  const applyView = useRef<(v: View, reframe: boolean) => void>(() => {});
  const floorId = view.activeId;
  const share = useRef<string | null>(null); // read-only link token
  const [shared, setShared] = useState<boolean | null>(null); // null until the URL is read; true: opened through a share link (no account pages)
  const projectTarget = (m: Manifest) => ({
    stem: m.name,
    loads: sortFloors(m.floors).map((f) => ({ id: f.id, url: glbUrl(f.generation_id, share.current) })),
  });

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
      // a past version has no building data (it describes the current state): its floors keep their stored offsets
      Promise.all([getProject(project, fetch, version, share.current), version === undefined ? getBuilding(project, fetch, share.current) : null]).then(([r, br]) => {
        const m = r.ok ? parseManifest(r.manifest) : null;
        if (!r.ok || !m) return setStatus(r.ok ? "error: malformed project manifest" : `error: ${r.message}`);
        if (br && !br.ok) return setStatus(`error: ${br.message}`);
        setViewing(version ?? null);
        const f = pickFloor(m, query.get("floor"));
        if (!f) return setStatus("error: project has no floors yet");
        lowestMm.current = Math.min(...m.floors.map((x) => x.elevation.value));
        setManifest(m);
        setBuilding(br?.ok ? br.building : manifestBuilding(m));
        // ?floor= keeps showing just that floor (as before); without it the whole building
        setView({ mode: query.get("floor") ? "isolate" : "whole", activeId: f.id, gap: GAP.default, ghost: false });
        setTarget(projectTarget(m));
      });
    } else if (generation !== null) {
      if (!isGenerationId(generation)) return queueMicrotask(() => setStatus("error: invalid generation id"));
      queueMicrotask(() => setTarget({ stem: `generation ${generation.slice(0, 8)}`, loads: [{ id: null, url: glbUrl(generation) }] }));
    } else {
      const name = resolveStem(query.get("model"));
      if (name === null) return queueMicrotask(() => setStatus("error: invalid model name (allowed: letters, digits, _ and -)"));
      queueMicrotask(() => setTarget({ stem: name, loads: [{ id: null, url: `/models/${name}.glb` }] }));
    }
  }, []);

  // Rooms live in the canonical JSON, not the GLB: list them for the loaded model (API models only).
  const roomsUrl = (target?.loads.find((l) => l.id === floorId) ?? target?.loads[0])?.url;
  useEffect(() => {
    if (!roomsUrl || !roomsUrl.includes("/artifacts/glb")) return queueMicrotask(() => setRooms([]));
    let live = true;
    fetch(canonicalUrl(roomsUrl), { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => live && setRooms(c?.buildings?.[0]?.floors?.[0]?.rooms ?? []))
      .catch(() => live && setRooms([]));
    return () => {
      live = false;
    };
  }, [roomsUrl]);

  // the scene reads the current view and building through refs; changing either re-places the floors
  useEffect(() => {
    viewRef.current = view;
    buildingRef.current = building;
    applyView.current(view, false);
  }, [view, building]);

  useEffect(() => {
    if (!target) return;
    const { loads, stem } = target;
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

    // the lights are data (lib/lighting.ts); walk mode adds a fill so the roof underside and ceilings show
    scene.add(new THREE.HemisphereLight(SKY_LIGHT.sky, SKY_LIGHT.ground, SKY_LIGHT.intensity));
    const sun = new THREE.DirectionalLight(SUN_LIGHT.color, SUN_LIGHT.intensity);
    sun.position.set(...SUN_LIGHT.dir);
    scene.add(sun);
    const fill = new THREE.AmbientLight(WALK_FILL.color, WALK_FILL.intensity);
    let grid = new THREE.GridHelper(20, 20); // 1 cell = 1 m; resized to the model once loaded
    scene.add(grid);
    scene.add(new THREE.AxesHelper(2)); // R=X, G=Y(up), B=Z

    // --- selection: click (not drag) picks a mesh; a hit inside a wall's aperture picks the opening
    let model: THREE.Object3D | null = null;
    let disposed = false;
    const roots = new Map<string | null, THREE.Object3D>(); // one model per floor, placed by applyView
    // floors that can be picked or measured: drawn at full strength
    const pickable = () => [...roots.values()].filter((r) => r.visible && !r.userData.ghost);
    const rootOf = (o: THREE.Object3D) => {
      for (let p: THREE.Object3D | null = o; p; p = p.parent) if (p.userData?.floorRoot) return p;
      return null;
    };
    const doors: Door[] = [];
    let hintTimer: ReturnType<typeof setTimeout> | undefined;
    const notify = (msg: string) => {
      setHint(msg);
      clearTimeout(hintTimer);
      hintTimer = setTimeout(() => setHint(null), 4000);
    };
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
    const showOpening = (o: OpeningData, thicknessMm: number, baseY: number, shift: THREE.Vector2) => {
      overlay = new THREE.Mesh(
        new THREE.BoxGeometry(1, 1, 1),
        new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.45 }),
      );
      const box = openingBox(o, thicknessMm, baseY, shift);
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
    // a door or window under a double click/tap: toggle a door (orbit and walk); say why when it cannot
    const toggleOpening = (o: OpeningData, pool: Door[]) => {
      const why = whyNoToggle(o, pool);
      if (why) return notify(why);
      const d = doorFor(pool, o.id)!;
      if (walk && distanceToOpening(d, walk.pos) > DOOR.reach) return notify("Too far from the door: walk closer.");
      if (walk && d.open && !canClose(d, walk.pos)) return notify("Step out of the doorway first.");
      toggleDoor(d);
    };
    // A single click selects after a short wait (cancelled by a second click); a double click on a door
    // only toggles it: it neither selects nor opens the properties. Measuring needs no wait.
    const gate = createTapGate();
    const select = (ray: THREE.Ray) => {
      if (!model || walk) return;
      const pick = pickElement(pickable(), ray);
      clearSelection();
      if (!pick) return setPanel(null);
      const ud = pick.mesh.userData as ElementData;
      if (pick.opening) {
        // opening selected: overlay only, so the host wall is not shown as selected too
        showOpening(pick.opening, ud.thickness?.value ?? 0, pick.baseY, pick.shift);
        return setPanel(describeOpening(pick.opening));
      }
      const mat = (pick.mesh.material as THREE.MeshStandardMaterial).clone();
      mat.emissive.set(0xffaa00);
      mat.emissiveIntensity = 0.6;
      selected = { mesh: pick.mesh, original: pick.mesh.material };
      pick.mesh.material = mat;
      setPanel(describeElement(ud));
    };
    const onUp = (e: PointerEvent) => {
      if (!down || !model || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
      const r = canvas.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1),
        camera,
      );
      const ray = raycaster.ray.clone();
      if (measureOn) {
        const pick = pickElement(pickable(), ray);
        return pick && measureClick(pick.mesh, pick.point);
      }
      gate.tap(
        { t: performance.now(), x: e.clientX, y: e.clientY },
        () => select(ray),
        () => {
          const hit = model && pickElement(pickable(), ray);
          if (hit?.opening) toggleOpening(hit.opening, doors.filter((d) => d.root === rootOf(hit.mesh)));
          else select(ray); // a double click elsewhere behaves like a click
        },
      );
    };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointerup", onUp);

    // --- walk mode (T23): WASD/arrows move, drag looks around, Esc or the button exits
    const keys = new Set<string>();
    let walk: {
      pos: THREE.Vector3;
      floorY: number; // the walker's feet: on the ground, or falling towards it
      groundY: number; // the ground height under the walker (what the feet fall or step to)
      vy: number; // fall speed
      eyeY: number; // the smoothed height of the eye above that ground (stairs and ramps glide)
      yaw: number;
      pitch: number;
      colliders: THREE.Mesh[];
      supports: THREE.Mesh[]; // surfaces that can be stood on: floors, stair steps, ramps, balconies
      baseY: number; // the floor level the walk started at; where the walker lands off any surface
      stepUp: number; // m: the highest step taken without a ramp (the stairs' own riser)
      restore: () => void;
      saved: { position: THREE.Vector3; target: THREE.Vector3 };
    } | null = null;
    let look: { x: number; y: number } | null = null;
    const aim = () => {
      if (!walk) return;
      camera.position.set(walk.pos.x, walk.eyeY, walk.pos.z);
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
      setWalkFill(scene, fill, false);
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
      const v = viewRef.current;
      const b = buildingRef.current;
      if (v.mode === "exploded") return notify("Walking needs the floors stacked: choose Whole building or Isolate floor.");
      // the floors the walker can reach: shown at full strength and joined by paired stairs (no pairing, no passage)
      const ids = b && v.activeId ? walkableFloors(b, v) : null;
      const walkRoots = ids ? [...ids].flatMap((i) => roots.get(i) ?? []) : [...roots.values()];
      const home = roots.get(v.activeId) ?? walkRoots[0];
      const spawn = home && spawnPoint(home);
      if (!spawn) return setStatus("walk mode needs a floor boundary in the model");
      setMeasure(false);
      clearSelection();
      setPanel(null);
      // an unpaired stair is a solid block: neither climbed nor walked through
      const blocked = b ? blockedStairs(b) : new Set<string>();
      const isBlocked = (m: THREE.Mesh) => m.userData?.type === "stair" && blocked.has(`${m.userData.floor_id}/${m.userData.id}`);
      const surfaces = walkRoots.flatMap(collectSupports);
      const colliders = [...walkRoots.flatMap(collectColliders), ...surfaces.filter(isBlocked)];
      walk = {
        pos: spawn.pos,
        floorY: spawn.floorY,
        groundY: spawn.floorY,
        vy: 0,
        eyeY: spawn.floorY + WALK.eye,
        yaw: 0,
        pitch: 0,
        colliders,
        supports: surfaces.filter((m) => !isBlocked(m)),
        baseY: spawn.floorY,
        stepUp: Math.max(...walkRoots.map(stepUpLimit)),
        restore: makeDoubleSided([...colliders, ...doors.map((d) => d.leaf)]),
        saved: { position: camera.position.clone(), target: controls.target.clone() },
      };
      persp.layers.enable(CEILING_LAYER); // ceilings are drawn only while walking
      setWalkFill(scene, fill, true); // inside, down-facing surfaces get no sun or sky
      controls.enabled = false;
      setWalking(true);
      aim();
    };
    toggleWalk.current = () => (walk ? exitWalk() : enterWalk());
    // doors on the floor the walker is on (opening ids repeat from floor to floor)
    const doorsHere = () => {
      const b = buildingRef.current;
      if (!walk || !b) return doors;
      const fid = floorAtHeight(b, viewRef.current, walk.floorY);
      return doors.filter((d) => d.root?.userData.floorId === fid);
    };
    const onKey = (e: KeyboardEvent, down: boolean) => {
      if (e.key === "Escape" && down) return measureOn ? setMeasure(false) : exitWalk();
      if (down && walk && e.key.toLowerCase() === "e" && !e.repeat) {
        const here = doorsHere();
        const d = nearestDoor(here, walk.pos);
        if (!d) return notify("No door within reach.");
        return toggleOpening(d.opening, here);
      }
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
    let lastFrame = performance.now();
    let last = performance.now();
    let lastBlocked: string | null = null;
    const stepWalk = () => {
      const now = performance.now();
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!walk) return;
      // the eye eases to the exact ground height every frame (also when standing still or falling)
      // gravity: the feet fall to the ground under them (off a stair's side, a ramp's edge...) and land;
      // the eye eases below, so the landing is soft and nothing teleports
      // the ground is looked up again where the walker stands, every frame: a stale one (a swapped model, a
      // floor that changed) cannot leave them floating, they fall to what is really below
      const here = stepOnto(walk.pos.x, walk.pos.z, walk.floorY, 0, walk.supports, walk.baseY, walk.stepUp);
      if (here.ok) walk.groundY = here.ground;
      ({ feet: walk.floorY, vy: walk.vy } = fall(walk.floorY, walk.groundY, walk.vy, dt));
      const goal = walk.floorY + WALK.eye;
      if (Math.abs(walk.eyeY - goal) > 1e-4) {
        walk.eyeY = dampTo(walk.eyeY, goal, dt);
        aim();
      }
      const b = buildingRef.current;
      const fid = b && floorAtHeight(b, viewRef.current, walk.floorY);
      const stuck = b && fid ? blockedStairAt(b, fid, walk.pos.x, walk.pos.z) : null;
      const stuckKey = stuck ? `${fid}/${stuck.stair}` : null;
      if (stuckKey !== lastBlocked) {
        lastBlocked = stuckKey;
        if (stuck) notify(blockedHint(stuck));
      }
      const f = (keys.has("w") || keys.has("arrowup") ? 1 : 0) - (keys.has("s") || keys.has("arrowdown") ? 1 : 0);
      const r = (keys.has("d") || keys.has("arrowright") ? 1 : 0) - (keys.has("a") || keys.has("arrowleft") ? 1 : 0);
      if (!f && !r) return;
      const fx = -Math.sin(walk.yaw);
      const fz = -Math.cos(walk.yaw);
      const d = new THREE.Vector2(fx * f - fz * r, fz * f + fx * r).normalize().multiplyScalar(WALK.speed * dt);
      const from = walk.pos.clone();
      // walls and every door that is closed; an open door is passable at once
      moveWithCollision(walk.pos, d, walk.floorY, [...walk.colliders, ...blocking(doors)]);
      const step = stepOnto(walk.pos.x, walk.pos.z, walk.floorY, from.distanceTo(walk.pos), walk.supports, walk.baseY, walk.stepUp);
      if (!step.ok) walk.pos.copy(from); // a stair's side or riser, a ramp's side or underside, a too steep ramp
      else {
        walk.groundY = step.ground;
        if (step.ground > walk.floorY) walk.floorY = step.ground; // a step up is taken at once (the eye eases it)
      }
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

    // every floor's model is loaded once; applyView places, shows and ghosts them without reloading
    const frame = (reframe: boolean) => {
      if (!model) return new THREE.Box3();
      const box = new THREE.Box3();
      roots.forEach((r) => r.visible && box.union(modelBox(r)));
      if (box.isEmpty()) box.copy(modelBox(model));
      const s = box.getSize(new THREE.Vector3());
      center = box.getCenter(new THREE.Vector3());
      size = Math.max(s.x, s.z);
      planBox = box;
      // grid extends well past the model (3x its larger side, min 20 m, even cell count)
      const cells = Math.max(20, Math.ceil((size * 3) / 2) * 2);
      scene.remove(grid);
      grid.dispose();
      grid = new THREE.GridHelper(cells, cells);
      // at the floor level (top of the slab), not the model's lowest point: the slab is below grade
      grid.position.set(center.x, Math.min(groundLevel(model, lowestMm.current), box.max.y) - 0.002, center.z);
      scene.add(grid);
      Object.assign(controls, orbitLimits(box));
      if (camera === ortho) fitPlan();
      else if (reframe) place(false);
      return box;
    };
    applyView.current = (v, reframe) => {
      if (!model) return;
      const b = buildingRef.current;
      const lift = b ? placements(b, v) : null;
      for (const [id, root] of roots) {
        const at = (id !== null && lift?.get(id)) || { x: 0, y: 0, z: 0 };
        root.position.set(at.x, at.y, at.z);
        const state = id !== null && b ? floorState(v, id) : "visible";
        root.visible = state !== "hidden";
        setGhost(root, state === "ghost");
      }
      model.updateMatrixWorld(true);
      clearSelection();
      setPanel(null);
      frame(reframe);
    };
    const loader = new GLTFLoader();
    Promise.all(loads.map((l) => loader.loadAsync(l.url)))
      .then((gltfs) => {
        if (disposed) return;
        const group = new THREE.Group();
        scene.add(group);
        model = group;
        gltfs.forEach((g, i) => {
          const root = g.scene;
          root.userData.floorRoot = true;
          root.userData.floorId = loads[i].id;
          group.add(root);
          roots.set(loads[i].id, root);
          layerCeilings(root);
          doors.push(...buildDoors(root));
          applyCeilingVisibility(root, true); // ceilings share the roof's underside plane: the roof shows instead
        });
        setRoofPresent([...roots.values()].some(hasRoof)); // only the top floor has one
        setRoofOn(true);
        setRoof.current = (on) =>
          roots.forEach((r) => {
            setRoofVisible(r, on);
            applyCeilingVisibility(r, on); // roof off: open to the sky, so no ceilings either
          });
        applyView.current(viewRef.current, false);
        const s = frame(true).getSize(new THREE.Vector3());
        setStatus(`${stem}: ${s.x.toFixed(2)} × ${s.z.toFixed(2)} × ${s.y.toFixed(2)} m (X × Z × H)`);
      })
      .catch(() => setStatus(`error: could not load ${loads.map((l) => l.url).join(", ")} (missing, unreachable or not a valid GLB). For API models check the backend is running; for ?model= build it and copy it to apps/web/public/models/`));

    renderer.setAnimationLoop(() => {
      const t = performance.now();
      animateDoors(doors, Math.min(0.05, (t - lastFrame) / 1000));
      lastFrame = t;
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
      disposed = true;
      applyView.current = () => {};
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
      gate.cancel(); // a pending single click must not run on a disposed scene
      clearTimeout(hintTimer);
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

  // The model of a project floor can be regenerated elsewhere (Parameters tab, another tab): when this
  // tab regains focus, reload the manifest and building, and reload the models if a floor changed.
  useEffect(() => {
    if (!manifest || viewing !== null) return;
    const key = (m: Manifest) => sortFloors(m.floors).map((f) => `${f.id}:${f.generation_id}`).join();
    const onFocus = () =>
      Promise.all([getProject(manifest.id, fetch, undefined, share.current), getBuilding(manifest.id, fetch, share.current)]).then(([r, br]) => {
        const m = r.ok ? parseManifest(r.manifest) : null;
        if (!m || !br.ok || m.floors.length === 0) return;
        setBuilding(br.building); // offsets and pairings may have changed
        if (key(m) === key(manifest)) return;
        lowestMm.current = Math.min(...m.floors.map((x) => x.elevation.value));
        setManifest(m);
        setView((v) => (m.floors.some((f) => f.id === v.activeId) ? v : { ...v, activeId: pickFloor(m, null)!.id }));
        setTarget(projectTarget(m));
      });
    const onVisible = () => document.visibilityState === "visible" && onFocus();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible); // coming back to this browser tab
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [manifest, viewing]);

  const floors = manifest ? sortFloors(manifest.floors) : [];
  const current = floors.find((f) => f.id === floorId);
  // the floor switcher picks the active floor (the one isolated, spawned in, and described); no reload
  const selectFloor = (f: Floor) => {
    if (!manifest || f.id === floorId) return;
    setPanel(null);
    setView((v) => ({ ...v, activeId: f.id }));
    applyView.current({ ...viewRef.current, activeId: f.id }, true);
    if (viewRef.current.mode === "isolate") window.history.replaceState(null, "", viewerUrl(manifest.id, f.id, viewing ?? undefined, share.current));
  };
  const changeView = (v: View, reframe: boolean) => {
    setView(v);
    applyView.current(v, reframe);
    if (manifest && v.activeId && v.mode === "isolate") window.history.replaceState(null, "", viewerUrl(manifest.id, v.activeId, viewing ?? undefined, share.current));
  };
  const activeFloor = building?.floors.find((f) => f.id === floorId);

  return (
    <div style={{ position: "fixed", inset: 0 }}>
      <div ref={mount} style={{ width: "100%", height: "100%" }} />
      <div style={{ position: "absolute", top: 12, left: 12, color: "#eee", font: "14px monospace" }}>
        <ViewerToolbar
          walking={walking}
          top={top}
          measuring={measuring}
          roofPresent={roofPresent}
          roofOn={roofOn}
          onWalk={() => toggleWalk.current()}
          onRoof={() => {
            setRoofOn(!roofOn);
            setRoof.current(!roofOn);
          }}
          onTop={() => {
            setTopState(!top);
            setTop.current(!top);
          }}
          onMeasure={() => toggleMeasure.current()}
        />
        {walking ? "WASD/arrows move, drag to look, E opens a door" : status}
        {hint && <div role="status" style={{ color: "#ffcc66" }}>{hint}</div>}
        <ViewerNav shared={shared} manifest={manifest} viewing={viewing} />
        {building && building.floors.length > 1 && (
          <BuildingControls view={view} disabled={walking} onChange={changeView} />
        )}
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
        {building && <BuildingStats building={building} active={activeFloor} />}
        <RoomList rooms={rooms} onSelect={(r) => setPanel(describeRoom(r, current?.id))} />
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
