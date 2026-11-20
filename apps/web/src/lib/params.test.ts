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
  wallHeight: "",
  units: "",
  doorHeight: "",
  windowHeight: "",
  windowSill: "",
  ...o,
});

test("required wall height missing -> error, nothing submitted", () => {
  expect(buildRequest(pre(["wall_height"]), form())).toEqual({ ok: false, errors: ["Wall height is required"] });
});

test("required units missing -> error", () => {
  const r = buildRequest(pre(["units"]), form({ wallHeight: "3000" }));
  expect(!r.ok && r.errors[0]).toMatch(/units are required/i);
});

test("valid values become numeric params; blanks are omitted, not defaulted", () => {
  const r = buildRequest(pre(["wall_height", "units"]), form({ wallHeight: "3000", units: "m", windowSill: "0" }));
  expect(r).toEqual({ ok: true, params: { upload_id: "u", wall_height: 3000, units: "m", window_sill: 0 } });
});

test.each(["0", "-5", "abc", "NaN"])("bad wall height %s rejected", (v) => {
  expect(buildRequest(pre([]), form({ wallHeight: v })).ok).toBe(false);
});

test("negative sill rejected, unknown units rejected", () => {
  expect(buildRequest(pre([]), form({ windowSill: "-1" })).ok).toBe(false);
  expect(buildRequest(pre([]), form({ units: "parsecs" })).ok).toBe(false);
});
