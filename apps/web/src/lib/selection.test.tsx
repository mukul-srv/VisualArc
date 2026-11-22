// T20: metadata shown for a selection must correspond exactly to the selected element.
// Uses a real GLB built from fixture_openings and the canonical snapshot as ground truth.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, expect, test } from "vitest";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MetadataPanel } from "../components/MetadataPanel";
import { pickElement } from "./pick";
import { describeElement, describeOpening, describeRoom, pickOpening, type ElementData, type OpeningData } from "./selection";

const root = path.resolve(__dirname, "../../../..");
type Canon = {
  walls: { id: string; thickness: { value: number; source: string }; height: { value: number; source: string }; role: string; role_source: string; sources: { layer: string; entity_handle: string }[] }[];
  junctions: { id: string; wall_ids: string[] }[];
  openings: {
    id: string;
    wall_id: string;
    kind: string;
    span: { start: [number, number]; end: [number, number] };
    sill_height: { value: number };
    height: { value: number };
    sources: { layer: string; entity_handle: string }[];
  }[];
};
let scene: THREE.Group;
let canon: Canon;

const node = (id: string) => scene.getObjectByName(id) as THREE.Mesh;
const ud = (id: string) => node(id).userData as ElementData;
const refs = (s: { layer: string; entity_handle: string }[]) => s.map((r) => `${r.layer}:${r.entity_handle}`);

beforeAll(async () => {
  const out = mkdtempSync(path.join(tmpdir(), "sel-"));
  execFileSync(
    "uv",
    ["run", "python", "-m", "api.cli", "build", path.join(root, "fixtures/input/fixture_openings.dxf"), "--wall-height", "3000", "--ceiling-height", "3000", "--out", out],
    { cwd: path.join(root, "services/api"), stdio: "pipe" },
  );
  const buf = readFileSync(path.join(out, "fixture_openings.glb"));
  const gltf = await new GLTFLoader().parseAsync(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer, "");
  scene = gltf.scene;
  canon = JSON.parse(readFileSync(path.join(root, "fixtures/expected/fixture_openings.canonical.json"), "utf8")).buildings[0].floors[0];
}, 120_000);

test("every wall panel matches its canonical wall: values, provenance, sources", () => {
  expect(canon.walls.length).toBe(10);
  for (const w of canon.walls) {
    const p = describeElement(ud(w.id));
    expect(p.id).toBe(w.id);
    const row = (l: string) => p.rows.find((r) => r.label === l)!;
    expect(row("Thickness")).toMatchObject({ value: `${w.thickness.value} mm`, provenance: w.thickness.source });
    expect(row("Height")).toMatchObject({ value: `${w.height.value} mm`, provenance: w.height.source });
    expect(row("Role")).toMatchObject({ value: w.role, provenance: w.role_source });
    expect(row("Openings hosted").value).toBe(String(canon.openings.filter((o) => o.wall_id === w.id).length));
    expect(p.sources).toEqual(refs(w.sources));
  }
});

test("junction panel is inferred, lists its walls and has no source entities", () => {
  const j = canon.junctions[0];
  const p = describeElement(ud(j.id));
  expect(p.rows.find((r) => r.label === "Origin")!.provenance).toBe("inferred");
  expect(p.rows.find((r) => r.label === "Walls touched")!.value).toBe(j.wall_ids.join(", "));
  expect(p.sources).toEqual([]);
});

// A ray from inside each aperture along the wall axis hits the real jamb reveal; the pick
// must resolve to exactly that opening (checks the plan->glTF mapping on real geometry).
test("raycast onto each opening's jamb picks that opening and shows its own metadata", () => {
  expect(canon.openings.length).toBe(7);
  for (const o of canon.openings) {
    const wall = node(o.wall_id);
    const baseY = new THREE.Box3().setFromObject(wall).min.y;
    const [sx, sy] = o.span.start;
    const [ex, ey] = o.span.end;
    const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
    const midH = baseY + (o.sill_height.value + o.height.value / 2) / 1000;
    const origin = new THREE.Vector3((sx + ex) / 2000, midH, -(sy + ey) / 2000);
    const dir = alongX ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, -1);
    const hit = new THREE.Raycaster(origin, dir).intersectObject(wall, true)[0];
    expect(hit, `${o.id} jamb`).toBeDefined();
    const picked = pickOpening(wall.userData as ElementData, hit.point, baseY) as OpeningData;
    expect(picked?.id).toBe(o.id);
    const p = describeOpening(picked);
    expect(p.id).toBe(o.id);
    expect(p.rows.find((r) => r.label === "Host wall")!.value).toBe(o.wall_id);
    expect(p.rows.find((r) => r.label === "Sill height")!.value).toBe(`${o.sill_height.value} mm`);
    expect(p.rows.find((r) => r.label === "Height")!.value).toBe(`${o.height.value} mm`);
    expect(p.sources).toEqual([...refs(o.sources), ...(o as OpeningData).swing ? refs([(o as OpeningData).swing!.source]) : []]); // the swing arc is a source too
  }
});

test("hits on solid wall (beside or above an opening) pick no opening", () => {
  const o = canon.openings[0];
  const ow = ud(o.wall_id);
  const wall = node(o.wall_id);
  const baseY = new THREE.Box3().setFromObject(wall).min.y;
  const cx = (o.span.start[0] + o.span.end[0]) / 2000;
  const cz = -(o.span.start[1] + o.span.end[1]) / 2000;
  const above = { x: cx, y: baseY + (o.sill_height.value + o.height.value + 50) / 1000, z: cz };
  expect(pickOpening(ow, above, baseY)).toBeNull();
  const below = { x: cx, y: baseY + Math.max(0, o.sill_height.value - 50) / 1000, z: cz };
  if (o.sill_height.value > 50) expect(pickOpening(ow, below, baseY)).toBeNull();
});

test("panel text spells out provenance, incl. defaulted opening dimensions", () => {
  const o = canon.openings[0] as unknown as { id: string; wall_id: string };
  const open = ud(o.wall_id).openings!.find((x) => x.id === o.id)!;
  const html = renderToStaticMarkup(<MetadataPanel panel={describeOpening(open)} />);
  expect(html).toContain("[ASSUMED DEFAULT (not in the drawing)]"); // fixture gives no height/sill
  expect(html).toContain("[extracted from DXF]"); // offset and width come from the drawing
  expect(html).toContain(o.wall_id);
});

test("empty selection prompts instead of showing stale data", () => {
  expect(renderToStaticMarkup(<MetadataPanel panel={null} />)).toContain("Click a wall");
});

// Opus review finding: a click aimed into the aperture passes through the wall hole.
test("frontal ray through each aperture centre selects that opening (not what is behind)", () => {
  for (const o of canon.openings) {
    const wall = node(o.wall_id);
    const baseY = new THREE.Box3().setFromObject(wall).min.y;
    const [sx, sy] = o.span.start;
    const [ex, ey] = o.span.end;
    const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
    const cx = (sx + ex) / 2000;
    const cz = -(sy + ey) / 2000;
    const y = baseY + (o.sill_height.value + o.height.value / 2) / 1000;
    const origin = alongX ? new THREE.Vector3(cx, y, cz + 0.3) : new THREE.Vector3(cx - 0.3, y, cz);
    const dir = alongX ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(1, 0, 0);
    const pick = pickElement(scene, new THREE.Ray(origin, dir));
    expect(pick?.opening?.id, o.id).toBe(o.id);
    expect(pick?.mesh.name).toBe(o.wall_id);
  }
});

test("ray at solid wall beside an aperture selects the wall, not the opening", () => {
  for (const o of canon.openings) {
    const [sx, sy] = o.span.start;
    const [ex, ey] = o.span.end;
    const alongX = Math.abs(ex - sx) >= Math.abs(ey - sy);
    const wall = node(o.wall_id);
    const baseY = new THREE.Box3().setFromObject(wall).min.y;
    const y = baseY + (o.sill_height.value + o.height.value / 2) / 1000;
    const a = alongX ? ex : ey; // just beyond the span end, still on the host if room remains
    const d = a / 1000 + 0.05;
    const origin = alongX ? new THREE.Vector3(d, y, -sy / 1000 + 0.3) : new THREE.Vector3(ex / 1000 - 0.3, y, -d);
    const dir = alongX ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(1, 0, 0);
    const pick = pickElement(scene, new THREE.Ray(origin, dir));
    expect(pick?.opening?.id).not.toBe(o.id);
  }
});

test("ray that misses everything picks nothing", () => {
  expect(pickElement(scene, new THREE.Ray(new THREE.Vector3(100, 100, 100), new THREE.Vector3(0, 1, 0)))).toBeNull();
});

test("describeElement handles a ceiling with inferred elevation provenance", () => {
  const p = describeElement({
    id: "ceiling-001",
    type: "ceiling",
    floor_id: "floor-0",
    elevation: { value: 3000, unit: "mm", source: "inferred" },
    sources: [{ layer: "A-FLOR", entity_handle: "3D" }],
  });
  expect(p.title).toBe("Ceiling");
  expect(p.rows).toContainEqual({ label: "Elevation", value: "3000 mm", provenance: "inferred" });
  expect(p.sources).toEqual(["A-FLOR:3D"]);
});

test("describeRoom shows the name with its provenance and the area in m2 with inferred provenance", () => {
  const p = describeRoom({
    id: "room-001",
    name: "Kitchen",
    name_source: "source_extracted",
    area: { value: 12_000_000, unit: "mm2", source: "inferred" },
    label_sources: [{ layer: "A-ANNO-TEXT", entity_handle: "5A" }],
  }, "floor-0");
  expect(p.rows.find((r) => r.label === "Name")).toMatchObject({ value: "Kitchen", provenance: "source_extracted" });
  expect(p.rows.find((r) => r.label.startsWith("Area"))).toMatchObject({ value: "12.00 m²", provenance: "inferred" });
  expect(p.sources).toEqual(["A-ANNO-TEXT:5A"]);
});

test("describeOpening shows swing and nominal frame/leaf detail with provenance", () => {
  const m = (value: number, source: "source_extracted" | "defaulted") => ({ value, unit: "mm", source });
  const door = {
    id: "opening-003", kind: "door", wall_id: "wall-001", span: { start: [0, 0] as [number, number], end: [900, 0] as [number, number] },
    offset: m(0, "source_extracted"), width: m(900, "source_extracted"), height: m(2100, "defaulted"), sill_height: m(0, "defaulted"),
    sources: [{ layer: "A-DOOR", entity_handle: "10" }],
    swing: { hinge: "start", opens_toward: "+y", source: { layer: "A-DOOR", entity_handle: "39" } },
    detail: { frame_width: m(50, "defaulted"), panel: "leaf", panel_thickness: m(40, "defaulted") },
  } as OpeningData;
  const p = describeOpening(door);
  expect(p.rows.find((r) => r.label === "Swing")?.value).toContain("opens toward +y");
  expect(p.rows.find((r) => r.label === "Leaf thickness")).toMatchObject({ provenance: "defaulted" });
  expect(p.sources).toContain("A-DOOR:39");
  const bare = describeOpening({ ...door, swing: null });
  expect(bare.rows.find((r) => r.label === "Swing")?.value).toContain("not set");
});

test("describeElement shows columns and balconies with their parameter provenance", () => {
  const m = (value: number, source: "source_extracted" | "defaulted" | "user_provided") => ({ value, unit: "mm", source });
  const col = describeElement({ id: "col-002", type: "column", shape: "circle", radius: m(200, "source_extracted"), height: m(3000, "user_provided"), sources: [{ layer: "A-COLS", entity_handle: "3D" }] });
  expect(col.rows.find((r) => r.label === "Radius")).toMatchObject({ value: "200 mm", provenance: "source_extracted" });
  expect(col.rows.find((r) => r.label.startsWith("Height"))).toMatchObject({ provenance: "user_provided" });
  const bal = describeElement({ id: "balcony-001", type: "balcony", thickness: m(200, "defaulted"), railing_height: m(900, "defaulted"), railing_thickness: m(50, "defaulted"), sources: [{ layer: "A-BALC", entity_handle: "3E" }] });
  expect(bal.rows.find((r) => r.label === "Railing height")).toMatchObject({ value: "900 mm", provenance: "defaulted" });
  expect(bal.sources).toEqual(["A-BALC:3E"]);
});
