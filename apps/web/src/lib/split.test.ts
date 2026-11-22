import { expect, test } from "vitest";
import type { Preflight } from "./api";
import type { FormValues } from "./params";
import { bboxSize, buildSplitRequest, initialRows, type FloorCandidate } from "./split";

const cand = (key: string, x: number, w: number): FloorCandidate => ({
  key,
  bbox: { min: [x, 5], max: [x + w, 5 + 4000] },
  entity_counts: { LINE: 8 },
  proposed_offset: { x, y: 5, source: "inferred" },
});
const cs = [cand("cluster-1", 0, 6000), cand("cluster-2", 14000, 5000)];
const pre: Preflight = { upload_id: "u", issues: [], needs: [], inventory: { layers: [], entity_counts: {} }, floor_candidates: cs };
const form: FormValues = { buildingType: "commercial", wallHeight: "3000", ceilingHeight: "3000", units: "", doorHeight: "", windowHeight: "", windowSill: "" };
const filled = () => initialRows(cs).map((r, i) => ({ ...r, name: ["Ground", "First"][i], elevation: ["0", "3200"][i] }));

test("bbox size and prefilled rows: offsets proposed from the engine, elevation never guessed", () => {
  expect(bboxSize(cs[1])).toEqual({ width: 5000, height: 4000 });
  const rows = initialRows(cs);
  expect(rows.map((r) => [r.offsetX, r.offsetY, r.elevation])).toEqual([["0", "5", ""], ["14000", "5", ""]]);
});

test("valid confirmation builds the body; the upload id stays in the URL", () => {
  const r = buildSplitRequest(pre, form, filled(), " House ");
  if (!r.ok) throw new Error(r.errors.join());
  expect(r.body).toMatchObject({ project_name: "House", wall_height: 3000, ceiling_height: 3000 });
  expect("upload_id" in r.body).toBe(false);
  expect(r.body.floors[1]).toEqual({ key: "cluster-2", exclude: false, name: "First", elevation: 3200, offset_x: 14000, offset_y: 5 });
});

test("empty heights and empty elevations are omitted; building_type is sent", () => {
  const r = buildSplitRequest(pre, { ...form, wallHeight: "", ceilingHeight: "" }, initialRows(cs), "House");
  if (!r.ok) throw new Error(r.errors.join());
  expect(r.body.building_type).toBe("commercial");
  expect("wall_height" in r.body || "ceiling_height" in r.body).toBe(false);
  expect(r.body.floors[0]).toEqual({ key: "cluster-1", exclude: false, name: "cluster-1", offset_x: 0, offset_y: 5 });
});

test("rejects a bad elevation, duplicates, bad offsets and nothing-to-build", () => {
  const err = (rows: ReturnType<typeof filled>, name = "House") => {
    const r = buildSplitRequest(pre, form, rows, name);
    return r.ok ? "" : r.errors.join("|");
  };
  const rows = filled();
  expect(err([{ ...rows[0], elevation: "abc" }, rows[1]])).toMatch(/elevation/);
  expect(err([rows[0], { ...rows[1], name: " ground " }])).toMatch(/names must be unique/);
  expect(err([rows[0], { ...rows[1], elevation: "0" }])).toMatch(/elevations must be unique/);
  expect(err([rows[0], { ...rows[1], offsetX: "abc" }])).toMatch(/offsets/);
  expect(err(rows, " ")).toMatch(/Project name/);
  expect(err(rows.map((r) => ({ ...r, exclude: true })))).toMatch(/at least one floor/);
});

test("an excluded floor needs no name or elevation and is sent as excluded", () => {
  const rows = [filled()[0], { ...initialRows(cs)[1], exclude: true }];
  const r = buildSplitRequest(pre, form, rows, "House");
  if (!r.ok) throw new Error(r.errors.join());
  expect(r.body.floors[1]).toEqual({ key: "cluster-2", exclude: true });
});
