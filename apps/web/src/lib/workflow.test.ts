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
  process.env.NEXT_PUBLIC_API_URL = base; // read at import time by lib/api
  api = await import("./api");
  server = spawn("uv", ["run", "uvicorn", "api.main:app", "--port", String(port)], {
    cwd: path.join(root, "services/api"),
    env: { ...process.env, API_DATA_DIR: mkdtempSync(path.join(tmpdir(), "wf-")) },
    stdio: "ignore",
  });
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${base}/health`)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("API did not start");
}, 60_000);

afterAll(() => {
  if (!server?.pid) return;
  // uv spawns the real server as a child; on Windows kill the whole tree
  if (process.platform === "win32") execSync(`taskkill /pid ${server.pid} /T /F`, { stdio: "ignore" });
  else server.kill();
});

test("success path: openings fixture -> viewer-loadable GLB with metadata", async () => {
  const up = await api.uploadDxf(fixture("fixture_openings.dxf"));
  if (!up.ok) throw new Error(up.message);
  expect(up.needs).toEqual(["ceiling_height", "wall_height"]); // preflight asks; nothing is guessed

  // blocked first: structured issues reach the web client intact
  const blocked = await api.generate({ upload_id: up.upload_id });
  expect(blocked).toMatchObject({ ok: false, kind: "blocked" });
  expect(!blocked.ok && blocked.issues.map((i) => i.code)).toContain("wall_height_missing");

  const gen = await api.generate({ upload_id: up.upload_id, wall_height: 3000, ceiling_height: 3000 });
  if (!gen.ok) throw new Error(gen.message);
  expect(api.isGenerationId(gen.generation_id)).toBe(true);

  const gltf = await loadGlb(api.glbUrl(gen.generation_id));
  const size = new THREE.Box3().setFromObject(gltf.scene).getSize(new THREE.Vector3());
  expect(size.x).toBeCloseTo(9.6, 3);
  expect(size.y).toBeCloseTo(3.0, 3);
  expect(size.z).toBeCloseTo(4.0, 3);

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
    expect(box.min.y).toBeCloseTo(f.elevation.value / 1000, 3); // elevation is already in the GLB
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
