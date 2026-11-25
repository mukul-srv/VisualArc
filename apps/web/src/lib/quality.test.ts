import { expect, test } from "vitest";
import { DEFAULT_QUALITY, QUALITY, QUALITY_IDS, shadowFrustum } from "./quality";

test("presets get heavier from low to high; accuracy is flat", () => {
  expect(QUALITY_IDS).toEqual(["low", "medium", "high", "accuracy"]);
  expect(QUALITY.low.shadowMap).toBe(0);
  expect(QUALITY.medium.shadowMap).toBeGreaterThan(0);
  expect(QUALITY.high.shadowMap).toBeGreaterThan(QUALITY.medium.shadowMap);
  expect(QUALITY.high.ssao && !QUALITY.medium.ssao).toBe(true);
  const a = QUALITY.accuracy;
  expect([a.shadowMap, a.ssao, a.env, a.textures, a.artificial]).toEqual([0, false, false, false, false]);
  expect(QUALITY[DEFAULT_QUALITY]).toBeDefined();
});

test("shadow frustum encloses the bounds from any direction", () => {
  const { centre, radius } = shadowFrustum([0, 0, -4], [10, 6, 0]);
  expect(centre).toEqual([5, 3, -2]);
  expect(radius).toBeCloseTo(Math.hypot(10, 6, 4) / 2);
  expect(shadowFrustum([0, 0, 0], [0, 0, 0]).radius).toBe(1);
});
