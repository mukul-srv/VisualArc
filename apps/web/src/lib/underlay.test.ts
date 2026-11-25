import { expect, test } from "vitest";
import { calibrationScale, imageRect, mmPerPx, planToPx, pxToPlan, type Underlay } from "./underlay";

const u = (m?: number): Underlay => ({
  url: "/u", width_px: 400, height_px: 300,
  calibration: m === undefined ? null : { p1: [0, 0], p2: [100, 0], distance_mm: 100 * m, mm_per_px: m, source: "user_provided" },
});

test("two clicks and a real distance give mm per pixel", () => {
  expect(calibrationScale([0, 0], [300, 400], 5000)).toEqual({ ok: true, mmPerPx: 10 }); // 500 px apart
  expect(calibrationScale([10, 10], [10, 110], 2500)).toEqual({ ok: true, mmPerPx: 25 });
});

test("bad calibrations are refused, never guessed", () => {
  for (const d of [0, -1, Infinity, NaN]) expect(calibrationScale([0, 0], [100, 0], d).ok).toBe(false);
  const near = calibrationScale([0, 0], [3, 4], 1000);
  expect(near.ok).toBe(false);
  expect(near.ok === false && near.error).toMatch(/5\.0 px apart/);
});

test("pixels and plan mm convert both ways, y flipped", () => {
  const c = u(20);
  expect(mmPerPx(c)).toBe(20);
  expect(pxToPlan(c, 0, 300)).toEqual([0, 0]); // bottom-left of the picture is the plan origin
  expect(pxToPlan(c, 400, 0)).toEqual([8000, 6000]);
  const back = planToPx(c, ...pxToPlan(c, 123, 45));
  expect(back[0]).toBeCloseTo(123);
  expect(back[1]).toBeCloseTo(45);
  expect(imageRect(c)).toEqual({ x0: 0, y0: 0, x1: 8000, y1: 6000 });
});

test("an uncalibrated picture is shown at 1 px = 1 mm only to pick the points", () => {
  expect(mmPerPx(u())).toBe(1);
  expect(imageRect(u())).toEqual({ x0: 0, y0: 0, x1: 400, y1: 300 });
});
