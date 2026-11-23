import { expect, test } from "vitest";
import type { Preflight } from "./api";
import { buildRequest, type FormValues } from "./params";

const pre = (needs: Preflight["needs"]): Preflight => ({
  upload_id: "u",
  issues: [],
  needs,
  inventory: { layers: [], entity_counts: {} },
});
const form = (o: Partial<FormValues> = {}): FormValues => ({
  buildingType: "residential",
  wallHeight: "",
  ceilingHeight: "",
  units: "",
  doorHeight: "",
  windowHeight: "",
  windowSill: "",
  ...o,
});

test("empty form sends only building_type: heights are left to the backend presets", () => {
  expect(buildRequest(pre([]), form())).toEqual({ ok: true, params: { upload_id: "u", building_type: "residential" } });
  expect(buildRequest(pre([]), form({ buildingType: "commercial" }))).toEqual({
    ok: true,
    params: { upload_id: "u", building_type: "commercial" },
  });
});

test("required units missing -> error (units are never defaulted)", () => {
  const r = buildRequest(pre(["units"]), form());
  expect(!r.ok && r.errors[0]).toMatch(/units are required/i);
});

test("valid values become numeric params; blanks are omitted, not defaulted", () => {
  const r = buildRequest(pre(["units"]), form({ wallHeight: "3000", ceilingHeight: "2600", units: "m", windowSill: "0" }));
  expect(r).toEqual({
    ok: true,
    params: { upload_id: "u", building_type: "residential", wall_height: 3000, ceiling_height: 2600, units: "m", window_sill: 0 },
  });
});

test.each(["0", "-5", "abc", "NaN"])("bad wall height %s rejected", (v) => {
  expect(buildRequest(pre([]), form({ wallHeight: v })).ok).toBe(false);
});

test("negative sill rejected, unknown units rejected", () => {
  expect(buildRequest(pre([]), form({ windowSill: "-1" })).ok).toBe(false);
  expect(buildRequest(pre([]), form({ units: "parsecs" })).ok).toBe(false);
});

import { diffParameters } from "./parameters";

test("diffParameters sets changes, resets emptied user values, keeps untouched defaults", () => {
  const loaded = {
    ceiling_height: { value: 2700, unit: "mm", source: "defaulted" },
    slab_thickness: { value: 300, unit: "mm", source: "user_provided" },
    roof_pitch: { value: 30, unit: "deg", source: "defaulted" },
  } as const;
  const r = diffParameters({ ...loaded }, { ceiling_height: "2400", slab_thickness: "", roof_pitch: "30" });
  expect(r).toEqual({ ok: true, values: { ceiling_height: 2400, slab_thickness: null } });
  expect(diffParameters({ ...loaded }, { ceiling_height: "-1", slab_thickness: "300", roof_pitch: "90" }).ok).toBe(false);
});

import { legacyNotice } from "./parameters";

test("floors without stored settings get a clear message with an action, not a dead end", () => {
  expect(legacyNotice([], "p")).toBeNull();
  const one = legacyNotice(["Level 0"], "abc")!;
  expect(one.text).toContain("Level 0");
  expect(one.action).toMatch(/Add it again from the DXF/);
  expect(one.href).toBe("/new?project=abc");
  expect(legacyNotice(["A", "B"], "abc")!.text).toMatch(/These floors A, B .* they were/);
});
