import { expect, test } from "vitest";
import type { Preflight } from "./api";
import { buildRequest, ceilingReady, setCeilingHeight, setWallHeight, type FormValues } from "./params";

const pre = (needs: Preflight["needs"]): Preflight => ({
  upload_id: "u",
  issues: [],
  needs,
  inventory: { layers: [], entity_counts: {} },
});
const form = (o: Partial<FormValues> = {}): FormValues => ({
  wallHeight: "",
  ceilingHeight: "",
  ceilingConfirmed: false,
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

test("wall height prefills ceiling height, but unconfirmed prefill is not user-provided", () => {
  const f = setWallHeight(form(), "3000");
  expect(f.ceilingHeight).toBe("3000");
  expect(f.ceilingConfirmed).toBe(false);
  expect(ceilingReady(pre(["ceiling_height"]), f)).toBe(false);
  const r = buildRequest(pre(["wall_height", "ceiling_height"]), f);
  expect(!r.ok && r.errors).toEqual(["Confirm the ceiling height"]);
});

test("confirmed ceiling height is sent; editing it withdraws confirmation; own value is not overwritten", () => {
  let f = setCeilingHeight(setWallHeight(form(), "3000"), "2600");
  f = { ...f, ceilingConfirmed: true };
  expect(ceilingReady(pre(["ceiling_height"]), f)).toBe(true);
  expect(buildRequest(pre(["wall_height", "ceiling_height"]), f)).toEqual({
    ok: true,
    params: { upload_id: "u", wall_height: 3000, ceiling_height: 2600 },
  });
  expect(setWallHeight(f, "2800").ceilingHeight).toBe("2600");
  expect(setCeilingHeight(f, "2500").ceilingConfirmed).toBe(false);
});

test("required ceiling height missing -> not ready, error", () => {
  expect(ceilingReady(pre(["ceiling_height"]), form())).toBe(false);
  const r = buildRequest(pre(["ceiling_height"]), form());
  expect(!r.ok && r.errors).toEqual(["Ceiling height is required"]);
});
