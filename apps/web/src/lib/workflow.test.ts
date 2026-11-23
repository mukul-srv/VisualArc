// T19: integrated workflow against a REAL uvicorn process, using the web app's own
// API client and the same GLTFLoader the viewer uses. Unit tests cover the pieces
// (parsing, validation, geometry); this covers that they work together over HTTP:
// upload -> preflight -> blocked generation -> generation -> artifacts -> viewer load.
// shortcut: no browser/WebGL rendering (needs an unapproved dependency such as
// Playwright); the viewer step is GLTFLoader on the served bytes. Rendering is MC-6.
import { execSync, spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeAll, expect, test } from "vitest";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const root = path.resolve(__dirname, "../../../..");
const ORIGIN = "http://localhost:3000";
let server: ChildProcess;
let base: string;
let api: typeof import("./api");
let afterAllRestore = () => {};

const freePort = () =>
  new Promise<number>((resolve) => {
    const s = createServer().listen(0, "127.0.0.1", () => {
      const { port } = s.address() as { port: number };
      s.close(() => resolve(port));
    });
  });

const fixture = (name: string) =>
  new Blob([readFileSync(path.join(root, "fixtures/input", name))]);

async function loadGlb(url: string) {
  const res = await fetch(url, { headers: { Origin: ORIGIN } });
  expect(res.status).toBe(200);
  expect(res.headers.get("access-control-allow-origin")).toBe(ORIGIN);
  return new GLTFLoader().parseAsync(await res.arrayBuffer(), "");
}

beforeAll(async () => {
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  api = await import("./api");
  // The app calls same-origin `/api/*` (Next rewrites to the API) and the browser keeps the
  // session cookie. Emulate both here: prefix relative URLs with the test server and carry
  // the cookie by hand.
  // never touch the dev database `visual_arc`: the spawned API writes users, projects and sessions
  const dbUrl = process.env.DATABASE_URL;
  if (!dbUrl || /\/visual_arc(\?|$)/.test(dbUrl))
    throw new Error("workflow.test.ts writes to Postgres: set DATABASE_URL to a scratch database (not `visual_arc`), e.g. postgresql+psycopg://visual_arc:visual_arc@localhost:5432/visual_arc_agent");
  const realFetch = globalThis.fetch;
  let cookie = "";
  globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" && input.startsWith("/") ? base + input : input;
    const headers = new Headers(init.headers);
    if (cookie) headers.set("Cookie", cookie);
    const res = await realFetch(url, { ...init, headers });
    const set = res.headers.getSetCookie().find((c) => c.startsWith("session="));
    if (set) cookie = set.split(";")[0];
    return res;
  }) as typeof fetch;
  afterAllRestore = () => (globalThis.fetch = realFetch);
  server = spawn("uv", ["run", "uvicorn", "api.main:app", "--port", String(port)], {
    cwd: path.join(root, "services/api"),
    env: { ...process.env, API_DATA_DIR: mkdtempSync(path.join(tmpdir(), "wf-")) },
    stdio: "ignore",
  });
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${base}/health`)).ok) break;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  if (!(await fetch(`${base}/health`).catch(() => null))?.ok) throw new Error("API did not start");
  const auth = await import("./auth");
  const reg = await auth.register(`wf-${Date.now()}@example.com`, "workflow test password", "Workflow");
  if (!reg.ok) throw new Error(reg.message);
}, 60_000);

afterAll(() => {
  afterAllRestore();
  if (!server?.pid) return;
  // uv spawns the real server as a child; on Windows kill the whole tree
  if (process.platform === "win32") execSync(`taskkill /pid ${server.pid} /T /F`, { stdio: "ignore" });
  else server.kill();
});

test("success path: openings fixture -> viewer-loadable GLB with metadata", async () => {
  const up = await api.uploadDxf(fixture("fixture_openings.dxf"));
  if (!up.ok) throw new Error(up.message);
  expect(up.needs).toEqual([]); // heights are defaulted (tagged), never asked

  // blocked first: structured issues reach the web client intact (units still cannot be defaulted)
  const blocked = await api.generate({ upload_id: up.upload_id, units: "cm" });
  expect(blocked).toMatchObject({ ok: false, kind: "blocked" });
  expect(!blocked.ok && blocked.issues.map((i) => i.code)).toContain("units_conflict");

  const presets = await api.getPresets();
  expect(presets.ok && presets.presets.commercial.wall_height).toBe(3000);
  const assumed = await api.generate({ upload_id: up.upload_id, building_type: "commercial" });
  expect(assumed.ok && assumed.issues.map((i) => i.code)).toEqual(expect.arrayContaining(["wall_height_defaulted", "ceiling_height_defaulted"]));

  const gen = await api.generate({ upload_id: up.upload_id, wall_height: 3000, ceiling_height: 3000 });
  if (!gen.ok) throw new Error(gen.message);
  expect(api.isGenerationId(gen.generation_id)).toBe(true);

  const gltf = await loadGlb(api.glbUrl(gen.generation_id));
  const size = new THREE.Box3().setFromObject(gltf.scene).getSize(new THREE.Vector3());
  // the default gable roof (30 deg) adds 300 mm eaves a side and a ridge of (4.0 + 0.6) / 2 x tan 30 deg
  expect(size.x).toBeCloseTo(9.6 + 0.6, 3);
  expect(size.y).toBeCloseTo(0.2 + 3.0 + 2.3 * Math.tan(Math.PI / 6), 3); // slab + walls + ridge
  expect(size.z).toBeCloseTo(4.0 + 0.6, 3);

  // opening metadata made it through API -> GLB -> three.js userData
  let openings = 0;
  gltf.scene.traverse((o) => {
    const list = o.userData.openings as unknown[] | undefined;
    if (list) openings += list.length;
  });
  expect(openings).toBe(7);

  // the other artifacts are retrievable; unknown ones are not
  const report = await fetch(`${base}/api/v1/generations/${gen.generation_id}/artifacts/report`);
  expect(await report.text()).toContain("# Verification report");
  expect((await fetch(`${base}/api/v1/generations/${gen.generation_id}/artifacts/secret`)).status).toBe(404);
});

test("2-floor project: create, add floors, manifest, each floor GLB sits at its elevation", async () => {
  const { parseManifest, sortFloors } = await import("./project");
  const c = await api.createProject("House");
  if (!c.ok) throw new Error(c.message);
  const h = { wall_height: 3000, ceiling_height: 3000 };
  const add = async (file: string, floor_name: string, elevation: number) => {
    const up = await api.uploadDxf(fixture(file));
    if (!up.ok) throw new Error(up.message);
    return api.addFloor(c.project_id, { upload_id: up.upload_id, floor_name, elevation, ...h });
  };
  const upper = await add("fixture_openings.dxf", "First", 3200);
  const ground = await add("fixture_a.dxf", "Ground", 0);
  if (!upper.ok || !ground.ok) throw new Error("floor not added");
  expect(await add("fixture_b.dxf", "ground", 6400)).toMatchObject({ ok: false, kind: "rejected" }); // duplicate name

  const got = await api.getProject(c.project_id);
  if (!got.ok) throw new Error(got.message);
  const m = parseManifest(got.manifest)!;
  expect(sortFloors(m.floors).map((f) => f.name)).toEqual(["Ground", "First"]); // by elevation, not creation
  expect(m.floors).toHaveLength(2); // the rejected add left nothing behind
  for (const f of m.floors) {
    expect(f.elevation.source).toBe("user_provided");
    const box = new THREE.Box3().setFromObject((await loadGlb(api.glbUrl(f.generation_id))).scene);
    expect(box.min.y).toBeCloseTo(f.elevation.value / 1000, 3); // the elevation is the base: slab and walls start there
  }
});

test("consolidated DXF: preflight lists floors, generation blocks, confirm creates a 2-floor project", async () => {
  const { parseManifest, sortFloors } = await import("./project");
  const { initialRows, buildSplitRequest } = await import("./split");
  const up = await api.uploadDxf(fixture("fixture_f.dxf"));
  if (!up.ok) throw new Error(up.message);
  const cands = up.floor_candidates ?? [];
  expect(cands).toHaveLength(2);
  expect(up.issues.map((i) => i.code)).toEqual(expect.arrayContaining(["floor_split_unconfirmed", "content_not_reconstructed"]));
  expect(await api.generate({ upload_id: up.upload_id, wall_height: 3000, ceiling_height: 3000 })).toMatchObject({ ok: false, kind: "blocked" });

  const form = { buildingType: "residential" as const, wallHeight: "3000", ceilingHeight: "3000", units: "", doorHeight: "", windowHeight: "", windowSill: "" };
  const rows = initialRows(cands).map((r, i) => ({ ...r, name: ["Ground", "First"][i], elevation: ["0", "3200"][i] }));
  const req = buildSplitRequest(up, form, rows, "Consolidated");
  if (!req.ok) throw new Error(req.errors.join());
  const done = await api.splitUpload(up.upload_id, req.body);
  if (!done.ok) throw new Error(done.message);
  const got = await api.getProject(done.project_id);
  if (!got.ok) throw new Error(got.message);
  const m = parseManifest(got.manifest)!;
  expect(sortFloors(m.floors).map((f) => f.name)).toEqual(["Ground", "First"]);
  for (const f of m.floors) {
    const box = new THREE.Box3().setFromObject((await loadGlb(api.glbUrl(f.generation_id))).scene);
    expect(box.min.y).toBeCloseTo(f.elevation.value / 1000, 3);
  }
});

test("failure paths: non-DXF rejected cleanly; unknown upload and generation are 404", async () => {
  const bad = await api.uploadDxf(new Blob(["not a dxf at all"]));
  expect(bad).toMatchObject({ ok: false, kind: "rejected" });
  expect(!bad.ok && bad.message).not.toMatch(/Traceback|[A-Za-z]:\\|\/tmp\//);

  const unknown = await api.generate({ upload_id: "0".repeat(32), wall_height: 3000, ceiling_height: 3000 });
  expect(unknown).toMatchObject({ ok: false, kind: "error" });
  expect((await fetch(api.glbUrl("0".repeat(32)))).status).toBe(404);
});

test("CORS: disallowed origin gets no allow header", async () => {
  const res = await fetch(`${base}/health`, { headers: { Origin: "http://evil.example" } });
  expect(res.headers.get("access-control-allow-origin")).toBeNull();
});

test("changing a parameter regenerates the floor and the served GLB changes (real worker thread)", async () => {
  const jobs = await import("./jobs");
  const projects = await import("./projects");
  const created = await api.createProject("Params");
  if (!created.ok) throw new Error(created.message);
  const pid = (created as unknown as { project_id: string }).project_id;
  const up = await api.uploadDxf(fixture("fixture_a.dxf"));
  if (!up.ok) throw new Error(up.message);
  const add = await jobs.addFloorJob(pid, { upload_id: up.upload_id, floor_name: "Ground", elevation: 0, wall_height: 3000, ceiling_height: 3000 });
  if (!add.ok) throw new Error(add.message);
  const before = await api.getProject(pid);
  if (!before.ok) throw new Error(before.message);
  const gid0 = (before.manifest as { floors: { generation_id: string }[] }).floors[0].generation_id;
  const box0 = new THREE.Box3().setFromObject((await loadGlb(api.glbUrl(gid0))).scene);

  const changed = await jobs.changeParametersJob(pid, { slab_thickness: 400 });
  if (!changed.ok) throw new Error(changed.message);
  const after = await api.getProject(pid);
  if (!after.ok) throw new Error(after.message);
  const gid1 = (after.manifest as { floors: { generation_id: string }[] }).floors[0].generation_id;
  expect(gid1).not.toBe(gid0); // a new generation, so a new GLB url
  const box1 = new THREE.Box3().setFromObject((await loadGlb(api.glbUrl(gid1))).scene);
  expect(box0.min.y).toBeCloseTo(0, 3);
  expect(box1.min.y).toBeCloseTo(0, 3); // the base (grid) does not move...
  const surface = (scene: THREE.Object3D) => {
    let y = NaN;
    scene.traverse((o) => o.userData?.type === "floor_boundary" && (y = new THREE.Box3().setFromObject(o).max.y));
    return y;
  };
  expect(surface((await loadGlb(api.glbUrl(gid0))).scene)).toBeCloseTo(0.2, 3);
  expect(surface((await loadGlb(api.glbUrl(gid1))).scene)).toBeCloseTo(0.4, 3); // ...the finished floor rises with the 400 mm slab
  const p = await projects.getParameters(pid);
  expect(p).toMatchObject({ ok: true, slab_thickness: { value: 400, source: "user_provided" } });
}, 60_000);

// --- the viewer's own logic on real engine output (real server, real GLB) ---
async function generated(name: string, extra: Record<string, unknown> = {}) {
  const up = await api.uploadDxf(fixture(name));
  if (!up.ok) throw new Error(up.message);
  const gen = await api.generate({ upload_id: up.upload_id, ceiling_height: 2700, wall_height: 2700, ...extra } as never);
  if (!gen.ok) throw new Error(gen.message);
  const scene = (await loadGlb(api.glbUrl(gen.generation_id))).scene;
  scene.updateMatrixWorld(true);
  return scene;
}

test("slab and walls start together on the ground; the walked floor is the slab top", async () => {
  const { groundLevel } = await import("./ground");
  const scene = await generated("fixture_a.dxf");
  let slabMin = Infinity, slabMax = -Infinity, wallMin = Infinity, boundary = NaN;
  scene.traverse((o) => {
    const b = new THREE.Box3().setFromObject(o);
    if (o.userData?.type === "slab") { slabMin = Math.min(slabMin, b.min.y); slabMax = Math.max(slabMax, b.max.y); }
    if (o.userData?.type === "wall") wallMin = Math.min(wallMin, b.min.y);
    if (o.userData?.type === "floor_boundary") boundary = b.max.y;
  });
  expect(slabMin).toBeCloseTo(0, 6); // the slab starts on the ground...
  expect(wallMin).toBeCloseTo(slabMin, 6); // ...and so do the walls: a closed box, no gap, nothing below the grid
  expect(slabMax).toBeCloseTo(0.2, 6); // the slab fills base .. base + 200 mm
  expect(boundary).toBeCloseTo(slabMax, 6); // the floor you walk on is the slab top
  expect(groundLevel(scene)).toBeCloseTo(slabMin, 6); // the grid sits at that common base
});

test("a wall's aperture box starts at the finished floor, not at the wall's base", async () => {
  const { pickElement } = await import("./pick");
  const scene = await generated("fixture_openings.dxf");
  let wall: THREE.Mesh | undefined;
  scene.traverse((o) => (o.userData?.type === "wall" && o.userData.openings?.length && !wall ? (wall = o as THREE.Mesh) : null));
  const op = wall!.userData.openings[0];
  expect(wall!.userData.floor_offset_mm).toBeCloseTo(200);
  const mid = [(op.span.start[0] + op.span.end[0]) / 2000, -(op.span.start[1] + op.span.end[1]) / 2000];
  const aim = (y: number) => pickElement(scene, new THREE.Ray(new THREE.Vector3(mid[0], y, mid[1] + 3), new THREE.Vector3(0, 0, -1)));
  const lead = op.kind === "door" ? 0.05 : op.sill_height.value / 1000 + 0.05; // just above the opening's floor
  expect(aim(0.2 + lead)?.opening?.id).toBe(op.id); // inside the aperture, counted from the finished floor
  if (op.kind === "door") expect(aim(0.1)?.opening ?? null).toBeNull(); // in the wall's base, under the aperture
});

test("roof toggle: with default presets the roof underside is the ceiling, so the roof shows from inside and outside", async () => {
  const { applyCeilingVisibility, setRoofVisible } = await import("./roof");
  const scene = await generated("fixture_roofs.dxf", { building_type: "residential" });
  const camera = new THREE.PerspectiveCamera();
  camera.layers.enable(1); // walk mode also draws the ceiling layer
  const drawn = () => {
    const types = new Set<string>();
    scene.traverse((o) => (o as THREE.Mesh).isMesh && o.visible && camera.layers.test(o.layers) && types.add(o.userData.type));
    return types;
  };
  applyCeilingVisibility(scene, true);
  expect(drawn().has("roof")).toBe(true); // visible to the walking camera
  expect(drawn().has("ceiling")).toBe(false); // not drawn over it: no z-fight, roof underside overhead
  setRoofVisible(scene, false);
  applyCeilingVisibility(scene, false);
  expect(drawn().has("roof")).toBe(false);
  expect(drawn().has("ceiling")).toBe(false); // roof off: open to the sky
  setRoofVisible(scene, true);
  applyCeilingVisibility(scene, true);
  expect(drawn().has("roof")).toBe(true);
});

test("a ceiling lower than the roof is drawn under it", async () => {
  const { applyCeilingVisibility } = await import("./roof");
  const scene = await generated("fixture_roofs.dxf", { building_type: "residential", ceiling_height: 2400 });
  applyCeilingVisibility(scene, true);
  let ceiling = false;
  scene.traverse((o) => o.userData?.type === "ceiling" && o.visible && (ceiling = true));
  expect(ceiling).toBe(true);
});

test("walking up the real stair of fixture_stairs climbs to the top tread", async () => {
  const { collectSupports, resolveHeight, stepUpLimit } = await import("./ground");
  const scene = await generated("fixture_stairs.dxf", { ceiling_height: 3000, wall_height: 3000, building_type: "residential", stair_rise: 160, stair_run: 250 });
  const supports = collectSupports(scene);
  const limit = stepUpLimit(scene);
  expect(limit).toBeCloseTo(0.16 + 0.02); // from the stair's own riser
  const floor = 0.2; // finished floor: base 0 + the 200 mm slab
  let x = 0.3, feet = floor;
  while (x < 5.1) { // stays on the stair (x 0.45 .. 5.2)
    const nx = x + 0.05;
    const y = resolveHeight(nx, -1.0, feet, 0.05, supports, floor, limit);
    // plan y 1000 mm = three z -1.0, along the arrow
    expect(y).not.toBeNull();
    x = nx;
    feet = y as number;
  }
  expect(feet).toBeCloseTo(floor + 19 * 0.16, 3);
  // and the ramp slab (3200 over 4750 mm) is walkable too
  let rx = 0.35, rf = floor; // from the floor in front, where the ramp starts at x = 0.45
  while (rx < 5.1) { // the ramp spans x 0.45 .. 5.2
    const nx = rx + 0.05;
    const y = resolveHeight(nx, -3.0, rf, 0.05, supports, floor, limit);
    expect(y).not.toBeNull();
    rx = nx;
    rf = y as number;
  }
  expect(rf).toBeGreaterThan(2.5);
});

test("a door of fixture_openings opens about its hinge and becomes passable", async () => {
  const { blocking, animate, buildDoors, toggle } = await import("./doors");
  const scene = await generated("fixture_openings.dxf");
  const doors = buildDoors(scene);
  expect(doors.map((d) => d.opening.id).sort()).toEqual(["opening-003", "opening-004", "opening-007"]); // doors with swing arcs
  const d = doors.find((x) => x.opening.id === "opening-003")!;
  const closed = new THREE.Box3().setFromObject(d.leaf);
  expect(blocking(doors)).toContain(d.leaf);
  toggle(d);
  for (let i = 0; i < 80; i++) animate(doors, 0.02);
  const open = new THREE.Box3().setFromObject(d.leaf);
  expect(blocking(doors)).not.toContain(d.leaf);
  // hinged at the start (x = 7.55), opening toward +y (three -z): the leaf now runs along z, hung at x = 7.55
  expect(open.max.x - open.min.x).toBeLessThan(0.1);
  expect(closed.max.x - closed.min.x).toBeGreaterThan(0.7);
  expect(open.min.z).toBeLessThan(-0.7);
});
