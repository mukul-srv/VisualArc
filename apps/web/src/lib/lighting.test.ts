import { expect, test } from "vitest";
import { BASE_LIGHTS, BACKGROUND, contrastWithBackground, shade, WALK_FILL } from "./lighting";

const ROOF = 0x8a4b3c; // the roof's palette colour
const DOWN: [number, number, number] = [0, -1, 0]; // the roof underside, seen from inside
const UP: [number, number, number] = [0, 1, 0]; // the roof top, seen from outside

test("walking inside, the roof underside under the orbit lights is no brighter than the background (the bug)", () => {
  // headless Chrome render of the real model measured 28,19,22 against a 30,30,34 background
  expect(contrastWithBackground(shade(ROOF, DOWN, BASE_LIGHTS))).toBeLessThan(1);
  expect(contrastWithBackground(shade(ROOF, UP, BASE_LIGHTS))).toBeGreaterThan(2); // the top is fine
});

test("with the walk-mode fill light the underside is clearly brighter than the background", () => {
  const lit = shade(ROOF, DOWN, [...BASE_LIGHTS, WALK_FILL]);
  expect(contrastWithBackground(lit)).toBeGreaterThan(2.5);
  // and the other down-facing surface, the ceiling, stays readable too
  expect(contrastWithBackground(shade(0xf4f4f0, DOWN, [...BASE_LIGHTS, WALK_FILL]))).toBeGreaterThan(2.5);
});

test("the background is the viewer's", () => {
  expect(BACKGROUND).toBe(0x1e1e22);
});
