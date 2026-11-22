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
    expect(box.min.y).toBeCloseTo(f.elevation.value / 1000 - 0.2, 3); // elevation is in the GLB; the default 200 mm slab sits below it
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
    expect(box.min.y).toBeCloseTo(f.elevation.value / 1000 - 0.2, 3);
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
  expect(box0.min.y).toBeCloseTo(-0.2, 3);
  expect(box1.min.y).toBeCloseTo(-0.4, 3); // the 400 mm slab
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

test("slab top is flush with the floor and the ground level is the floor level (walls do not float)", async () => {
  const { groundLevel } = await import("./ground");
  const scene = await generated("fixture_a.dxf");
  let slabMin = Infinity, slabMax = -Infinity, wallMin = Infinity;
  scene.traverse((o) => {
    const b = new THREE.Box3().setFromObject(o);
    if (o.userData?.type === "slab") { slabMin = Math.min(slabMin, b.min.y); slabMax = Math.max(slabMax, b.max.y); }
    if (o.userData?.type === "wall") wallMin = Math.min(wallMin, b.min.y);
  });
  expect(slabMax).toBeCloseTo(0, 6); // the slab top is the floor elevation
  expect(wallMin).toBeCloseTo(slabMax, 6); // walls start on the slab top: no gap
  expect(slabMin).toBeCloseTo(-0.2, 6); // the slab is below grade
  expect(groundLevel(scene)).toBeCloseTo(0, 6); // the grid sits at the floor, not at the slab underside
  // the slab also lies under every wall, so none stands on air
  const slab = new THREE.Box3();
  const walls = new THREE.Box3();
  scene.traverse((o) => {
    if (o.userData?.type === "slab") slab.expandByObject(o);
    if (o.userData?.type === "wall") walls.expandByObject(o);
  });
  expect(slab.containsBox(new THREE.Box3(new THREE.Vector3(walls.min.x, slab.min.y, walls.min.z), new THREE.Vector3(walls.max.x, slab.max.y, walls.max.z)))).toBe(true);
});

test("with default presets the ceiling and the roof underside share a plane (the walk-mode z-fight), and the fix separates them", async () => {
  const { ceilingMeetsRoof, separateCoplanar } = await import("./roof");
  const scene = await generated("fixture_roofs.dxf", { building_type: "residential" });
  expect(ceilingMeetsRoof(scene)).toBe(true);
  separateCoplanar(scene);
  let offset = 0;
  scene.traverse((o) => o.userData?.type === "ceiling" && ((o as THREE.Mesh).material as THREE.Material).polygonOffset && offset++);
  expect(offset).toBeGreaterThan(0);
});

test("walking up the real stair of fixture_stairs climbs to the top tread", async () => {
  const { collectSupports, resolveHeight, stepUpLimit } = await import("./ground");
  const scene = await generated("fixture_stairs.dxf", { ceiling_height: 3000, wall_height: 3000, building_type: "residential", stair_rise: 160, stair_run: 250 });
  const supports = collectSupports(scene);
  const limit = stepUpLimit(scene);
  expect(limit).toBeCloseTo(0.16 + 0.02); // from the stair's own riser
  let x = 0.3, feet = 0;
  while (x < 5.1) { // stays on the stair (x 0.45 .. 5.2)
    const nx = x + 0.05;
    const y = resolveHeight(nx, -1.0, feet, 0.05, supports, 0, limit);
    // plan y 1000 mm = three z -1.0, along the arrow
    expect(y).not.toBeNull();
    x = nx;
    feet = y as number;
  }
  expect(feet).toBeCloseTo(19 * 0.16, 3);
  // and the ramp slab (3200 over 4750 mm) is walkable too
  let rx = 0.35, rf = 0; // from the floor in front, where the ramp starts at x = 0.45
  while (rx < 5.1) { // the ramp spans x 0.45 .. 5.2
    const nx = rx + 0.05;
    const y = resolveHeight(nx, -3.0, rf, 0.05, supports, 0, limit);
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
