"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { canonicalUrl, exportUrl, getProject, glbUrl, isGenerationId } from "@/lib/api";
import { getBuilding, sameBuilding, type Building } from "@/lib/building";
import { blockedHint, blockedStairAt, blockedStairs, floorAtHeight, floorState, GAP, manifestBuilding, placements, walkableFloors, type View } from "@/lib/building-view";
import { setGhost } from "@/lib/ghost";
import { BuildingControls, BuildingStats } from "@/components/BuildingControls";
import { parseManifest, pickFloor, sortFloors, viewerUrl, type Floor, type Manifest } from "@/lib/project";
import { resolveStem } from "@/lib/model-stem";
import { ViewerNav } from "@/components/ViewerNav";
import { MetadataPanel } from "@/components/MetadataPanel";
import { MaterialPicker } from "@/components/MaterialPicker";
import { applyMaterials, materialKey, putMaterials, textureCache, type MaterialMap } from "@/lib/materials";
import { RoomList } from "@/components/RoomList";
import { ViewerToolbar } from "@/components/ViewerToolbar";
import { orbitLimits, planFrustum } from "@/lib/camera";
import { openingFrame, pickElement } from "@/lib/pick";
import { animate as animateDoors, blocking, buildDoors, canClose, DOOR, distanceToOpening, doorFor, nearestDoor, toggle as toggleDoor, whyNoToggle, type Door } from "@/lib/doors";
import { collectSupports, dampTo, fall, groundLevel, stepOnto, stepUpLimit } from "@/lib/ground";
import { applyCeilingVisibility, hasRoof, setRoofVisible } from "@/lib/roof";
import { createTapGate } from "@/lib/tap";
import { setWalkFill, WALK_FILL } from "@/lib/lighting";
import { LightingPanel } from "@/components/LightingPanel";
import { DEFAULT_QUALITY, QUALITY, type QualityId } from "@/lib/quality";
import { createRig } from "@/lib/rig";
import { IDLE_RENDER, RenderPanel, type RenderState } from "@/components/RenderPanel";
import { beginStill, maxRenderDim, type Still } from "@/lib/render-gl";
import { cancelToken, CANCELLED } from "@/lib/pathtrace";
import { clampTrace, DEFAULT_TRACE, outputSize, stillName, type ResolutionId, type TraceSettings } from "@/lib/render-settings";
import { daylight, sunDirection, sunPosition } from "@/lib/solar";
import { NO_LIGHTING, putLighting, type SiteLighting } from "@/lib/site-lighting";
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
  const [generationId, setGenerationId] = useState<string | null>(null); // a standalone model (?generation=)
  const [materials, setMaterials] = useState<MaterialMap>({}); // "<floor>/<element>" -> library id
  const materialsRef = useRef<MaterialMap>({});
  const applyMats = useRef<(m: MaterialMap) => void>(() => {});
  const [quality, setQuality] = useState<QualityId>(DEFAULT_QUALITY);
  const [site, setSiteState] = useState<SiteLighting>(NO_LIGHTING); // edited copy; `savedSite` is what the project holds
  const [savedSite, setSavedState] = useState<SiteLighting>(NO_LIGHTING);
  const [nowMs, setNowMs] = useState(() => Date.now()); // the sun follows the clock (refreshed every minute)
  const [droppedLights, setDroppedLights] = useState(0);
  const [selLight, setSelLight] = useState<string | null>(null);
  const lightState = useRef({ site, nowMs, quality, selLight });
  const manifestRef = useRef<Manifest | null>(null);
  useEffect(() => {
    manifestRef.current = manifest;
  }, [manifest]);
  const applyLighting = useRef<() => void>(() => {});
  const [shareToken, setShareToken] = useState<string | null>(null); // the read-only link token, for render-time reads
  const [renderOpen, setRenderOpen] = useState(false);
  const [renderState, setRenderState] = useState<RenderState>(IDLE_RENDER);
  const [traceSettings, setTraceSettings] = useState<TraceSettings>(DEFAULT_TRACE);
  const renderApi = useRef<{ start: (s: TraceSettings) => void; stop: () => void; shot: (r: ResolutionId) => void; reset: () => void }>({ start() {}, stop() {}, shot() {}, reset() {} });
  const siteRef = useRef(site);
  const savedSiteRef = useRef(savedSite);
  // the refs change together with the state, so a poll callback never reads a stale copy
  const setSite = useCallback((s: SiteLighting) => {
    siteRef.current = s;
    setSiteState(s);
  }, []);
  const setSavedSite = useCallback((s: SiteLighting) => {
    savedSiteRef.current = s;
    setSavedState(s);
  }, []);
  const [picked, setPicked] = useState<{ floor: string | null; id: string; type: string } | null>(null);
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
    queueMicrotask(() => setShareToken(share.current));
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
        // no building data (API error): the floors still show, without offsets and pairings
        if (br && !br.ok) queueMicrotask(() => setHint("Building data unavailable: floors are shown without offsets or pairings."));
        setViewing(version ?? null);
        const f = pickFloor(m, query.get("floor"));
        if (!f) return setStatus("error: project has no floors yet");
        lowestMm.current = Math.min(...m.floors.map((x) => x.elevation.value));
        setManifest(m);
        setMaterials(m.materials ?? {});
        setSite(m.lighting ?? NO_LIGHTING);
        setSavedSite(m.lighting ?? NO_LIGHTING);
        setDroppedLights(m.lightingDropped ?? 0);
        setBuilding(br?.ok ? br.building : manifestBuilding(m));
        // ?floor= keeps showing just that floor (as before); without it the whole building
        setView({ mode: query.get("floor") ? "isolate" : "whole", activeId: f.id, gap: GAP.default, ghost: false });
        setTarget(projectTarget(m));
      });
    } else if (generation !== null) {
      if (!isGenerationId(generation)) return queueMicrotask(() => setStatus("error: invalid generation id"));
      queueMicrotask(() => setGenerationId(generation));
      queueMicrotask(() => setTarget({ stem: `generation ${generation.slice(0, 8)}`, loads: [{ id: null, url: glbUrl(generation) }] }));
    } else {
      const name = resolveStem(query.get("model"));
      if (name === null) return queueMicrotask(() => setStatus("error: invalid model name (allowed: letters, digits, _ and -)"));
      queueMicrotask(() => setTarget({ stem: name, loads: [{ id: null, url: `/models/${name}.glb` }] }));
    }
  }, [setSite, setSavedSite]);

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
    materialsRef.current = materials;
    applyMats.current(QUALITY[quality].textures ? materials : {}); // accuracy: no textures, plain palette
  }, [materials, quality]);

  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    lightState.current = { site, nowMs, quality, selLight };
    siteRef.current = site;
    savedSiteRef.current = savedSite;
    applyLighting.current();
  }, [site, nowMs, quality, selLight, savedSite]);

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
    const rig = createRig(scene, renderer); // sky, sun + shadows, reflections, ambient occlusion, user lights
    rig.resize(el.clientWidth, el.clientHeight);
    const fill = new THREE.AmbientLight(WALK_FILL.color, WALK_FILL.intensity);
    let grid = new THREE.GridHelper(20, 20); // 1 cell = 1 m; resized to the model once loaded
    scene.add(grid);
    const axes = new THREE.AxesHelper(2); // R=X, G=Y(up), B=Z
    scene.add(axes);

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
    const cache = textureCache();
    const highlight = (mesh: THREE.Mesh) => {
      const mat = (mesh.material as THREE.MeshStandardMaterial).clone();
      mat.emissive.set(0xffaa00);
      mat.emissiveIntensity = 0.6;
      selected = { mesh, original: mesh.material };
      mesh.material = mat;
    };
    applyMats.current = (map) => {
      const keep = selected?.mesh; // the highlight sits on a clone of the old material: redo it
      if (keep) clearSelection();
      roots.forEach((r, id) => applyMaterials(r, id, map, cache));
      if (keep) highlight(keep);
      applyView.current(viewRef.current, false); // new materials need the ghost state
    };
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
      const { box, yaw } = openingFrame(o, thicknessMm, baseY, shift);
      box.getCenter(overlay.position);
      box.getSize(overlay.scale);
      overlay.rotation.y = yaw;
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
      highlight(pick.mesh);
      setPicked({ floor: (rootOf(pick.mesh)?.userData.floorId as string | null) ?? null, id: ud.id, type: ud.type });
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
      rig.fit(box);
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
    let lastSky = 1;
    applyLighting.current = () => {
      const { site: st, nowMs: now, quality: ql, selLight: sel } = lightState.current;
      const q = QUALITY[ql];
      let sunDir: [number, number, number] | null = null;
      let day = { sun: 1, sky: 1 };
      if (q.artificial && st.location) {
        const p = sunPosition(st.location.latitude, st.location.longitude, now);
        sunDir = sunDirection(p.azimuth, p.elevation, st.north_deg);
        day = daylight(p.elevation);
      }
      lastSky = day.sky;
      rig.update(
        { quality: q, sunDir, sunStrength: day.sun, skyStrength: day.sky, lights: st.lights, selectedLight: sel },
        { rootOf: (id) => roots.get(id), elevationMm: (id) => manifestRef.current?.floors.find((f) => f.id === id)?.elevation.value ?? 0 },
      );
    };
    // --- render panel: path-traced still and realtime screenshot of the current view
    let still: Still | null = null;
    const epoch = cancelToken(); // closing the panel cancels a start that is still building
    let resultUrl: string | null = null;
    const dropResult = () => {
      if (resultUrl) URL.revokeObjectURL(resultUrl);
      resultUrl = null;
    };
    const sized = (res: ResolutionId) => {
      const sz = outputSize(res, { w: el.clientWidth, h: el.clientHeight }, maxRenderDim(renderer));
      return { sz, note: sz.clamped ? `The requested resolution was reduced to ${sz.w} x ${sz.h} px, the largest this GPU allows.` : null };
    };
    const finishWith = (blob: Blob | null, sz: { w: number; h: number }, kind: "render" | "screenshot", note: string | null) => {
      dropResult();
      if (!blob) return setRenderState({ ...IDLE_RENDER, phase: "error", message: "The browser could not produce the PNG." });
      resultUrl = URL.createObjectURL(blob);
      setRenderState({ ...IDLE_RENDER, phase: "done", size: sz, message: note, result: { url: resultUrl, name: stillName(stem, sz.w, sz.h, kind), kind } });
    };
    renderApi.current = {
      reset: () => {
        epoch.cancel();
        still?.dispose(); // stops the sampling loop first
        still = null;
        dropResult();
        setRenderState(IDLE_RENDER);
      },
      stop: () => still?.stop(),
      shot: async (res) => {
        if (still) return;
        clearSelection();
        const { sz, note } = sized(res);
        try {
          const blob = await rig.capture(scene, camera, persp, sz.w, sz.h);
          finishWith(blob, sz, "screenshot", note);
        } catch (e) {
          setRenderState({ ...IDLE_RENDER, phase: "error", message: `Screenshot failed: ${e instanceof Error ? e.message : String(e)}` });
        }
      },
      start: async (raw) => {
        if (still) return;
        const mine = epoch.next();
        const cancelled = () => !epoch.isCurrent(mine);
        const settings = clampTrace(raw);
        clearSelection();
        dropResult();
        const { sz, note } = sized(settings.resolution);
        setRenderState({ ...IDLE_RENDER, phase: "building", size: sz, message: note });
        try {
          const st = await beginStill({
            scene, camera, settings, size: sz, accuracy: lightState.current.quality === "accuracy", skyStrength: lastSky,
            hide: [grid, axes, rig.hemi, fill],
            isCancelled: cancelled,
            onStatus: (status) => setRenderState((r) => (r.phase === "building" || r.phase === "running" ? { ...r, phase: "running", status } : r)),
          });
          still = st;
          setRenderState((r) => ({ ...r, phase: "running", canvas: st.canvas }));
          await st.done;
          if (cancelled()) return; // closed meanwhile: reset() already disposed it
          const blob = await st.png();
          st.dispose();
          still = null;
          if (cancelled()) return;
          finishWith(blob, sz, "render", note);
        } catch (e) {
          if (e === CANCELLED || cancelled()) return; // closed while building: beginStill restored the scene
          still?.dispose();
          still = null;
          setRenderState({ ...IDLE_RENDER, phase: "error", size: sz, message: `Path tracing failed: ${e instanceof Error ? e.message : String(e)}` });
        }
      },
    };
    const applyAll = () => roots.forEach((r, id) => applyMaterials(r, id, materialsRef.current, cache));
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
          rig.prepare(root);
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
        applyAll();
        applyLighting.current();
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
      rig.render(scene, camera, persp);
    });
    const onResize = () => {
      persp.aspect = el.clientWidth / el.clientHeight;
      persp.updateProjectionMatrix();
      if (camera === ortho) fitPlan();
      rig.resize(el.clientWidth, el.clientHeight);
    };
    window.addEventListener("resize", onResize);
    return () => {
      disposed = true;
      applyView.current = () => {};
      applyMats.current = () => {};
      applyLighting.current = () => {};
      renderApi.current.reset();
      renderApi.current = { start() {}, stop() {}, shot() {}, reset() {} };
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
        (m.userData?.originalMaterial as THREE.Material | undefined)?.dispose();
      });
      cache.dispose();
      rig.dispose();
      renderer.setAnimationLoop(null);
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [target, setSite]);

  // The model of a project floor can be regenerated elsewhere (Parameters tab, another tab): when this
  // tab regains focus, reload the manifest and building, and reload the models if a floor changed.
  useEffect(() => {
    if (!manifest || viewing !== null) return;
    const key = (m: Manifest) => sortFloors(m.floors).map((f) => `${f.id}:${f.generation_id}`).join();
    const onFocus = () =>
      Promise.all([getProject(manifest.id, fetch, undefined, share.current), getBuilding(manifest.id, fetch, share.current)]).then(([r, br]) => {
        const m = r.ok ? parseManifest(r.manifest) : null;
        if (!m || !br.ok || m.floors.length === 0) return;
        setBuilding((old) => (sameBuilding(old, br.building) ? old : br.building)); // only when offsets or pairings changed
        const lt = m.lighting ?? NO_LIGHTING;
        if (JSON.stringify(savedSiteRef.current) !== JSON.stringify(lt)) {
          if (JSON.stringify(siteRef.current) === JSON.stringify(savedSiteRef.current)) setSite(lt); // unsaved edits are kept
          setSavedSite(lt);
          setDroppedLights(m.lightingDropped ?? 0);
        }
        setMaterials((old) => (JSON.stringify(old) === JSON.stringify(m.materials ?? {}) ? old : (m.materials ?? {})));
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
  }, [manifest, viewing, setSite, setSavedSite]);

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
  const canEdit = !!manifest && viewing === null && shared === false && (manifest.role === "owner" || manifest.role === "editor");
  const siteDirty = JSON.stringify(site) !== JSON.stringify(savedSite);
  const saveSite = async () => {
    if (!manifest) return;
    const r = await putLighting(manifest.id, site);
    if (r.ok) {
      setSavedSite(r.lighting);
      setDroppedLights(0); // the server now holds what is shown
    }
    else setHint(`Could not save lighting: ${r.message}`);
  };
  const sunPos = site.location && QUALITY[quality].artificial ? sunPosition(site.location.latitude, site.location.longitude, nowMs) : null;
  const changeMaterial = async (key: string, lib: string | null) => {
    if (!manifest) return;
    const old = materials;
    const next = { ...old };
    if (lib) next[key] = lib;
    else delete next[key];
    setMaterials(next);
    const r = await putMaterials(manifest.id, next);
    if (!r.ok) {
      setMaterials(old);
      setHint(`Could not save material: ${r.message}`);
    }
  };

  // exports are the current state, so not offered while looking at an older version
  const exportTarget = viewing !== null ? null : manifest ? { project: manifest.id } : generationId ? { generation: generationId } : null;
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
          exports={exportTarget && { obj: exportUrl(exportTarget, "obj", shareToken), ifc: exportUrl(exportTarget, "ifc", shareToken) }}
        />
        {walking ? "WASD/arrows move, drag to look, E opens a door" : status}
        {hint && <div role="status" style={{ color: "#ffcc66" }}>{hint}</div>}
        <ViewerNav shared={shared} manifest={manifest} viewing={viewing} standalone={generationId !== null} />
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
          maxHeight: "calc(100vh - 24px)", // taller than the window: scroll the panel, not the page
          overflowY: "auto",
          boxSizing: "border-box",
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
        <button disabled={walking || !target} onClick={() => setRenderOpen(true)}>
          Render / screenshot…
        </button>
        <LightingPanel
          quality={quality}
          onQuality={setQuality}
          site={site}
          onSite={setSite}
          droppedLights={droppedLights}
          sunInfo={sunPos ? `Sun: azimuth ${sunPos.azimuth.toFixed(0)} deg, elevation ${sunPos.elevation.toFixed(0)} deg${sunPos.elevation <= 0 ? " (night)" : ""}` : null}
          canSave={canEdit && manifest !== null}
          dirty={siteDirty}
          onSave={saveSite}
          projectId={manifest && viewing === null ? manifest.id : null}
          planFloors={sortFloors(manifest?.floors ?? []).map((f) => ({ id: f.id, name: f.name }))}
          share={shareToken}
          selectedId={selLight}
          onSelect={setSelLight}
          floorName={(id) => manifest?.floors.find((f) => f.id === id)?.name ?? id}
        />
        <MetadataPanel panel={panel} />
        {panel && picked && picked.id === panel.id && picked.floor && manifest && (
          <MaterialPicker
            type={picked.type}
            value={materials[materialKey(picked.floor, picked.id)] ?? null}
            disabled={!canEdit}
            onChange={(lib) => changeMaterial(materialKey(picked.floor!, picked.id), lib)}
          />
        )}
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
      {renderOpen && (
        <RenderPanel
          state={renderState}
          settings={traceSettings}
          onSettings={setTraceSettings}
          onStart={() => renderApi.current.start(traceSettings)}
          onStop={() => renderApi.current.stop()}
          onScreenshot={() => renderApi.current.shot(traceSettings.resolution)}
          onClose={() => {
            renderApi.current.reset();
            setRenderOpen(false);
          }}
        />
      )}
    </div>
  );
}
