import { expect, test } from "vitest";
import * as THREE from "three";
import { BASE_LIGHTS, BACKGROUND, contrastWithBackground, setWalkFill, shade, SKY_LIGHT, SUN_LIGHT, WALK_FILL } from "./lighting";

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

test("the viewer's lights are typed data: the orbit pair, and the walk fill is separate", () => {
  expect(BASE_LIGHTS).toEqual([SKY_LIGHT, SUN_LIGHT]);
  expect(BASE_LIGHTS).not.toContain(WALK_FILL); // the orbit view never has the fill
  expect(WALK_FILL.kind).toBe("ambient");
});

test("entering walk mode adds the fill light once, leaving removes it; any order is safe", () => {
  const scene = new THREE.Scene();
  const fill = new THREE.AmbientLight(WALK_FILL.color, WALK_FILL.intensity);
  const count = () => scene.children.filter((c) => c === fill).length;
  setWalkFill(scene, fill, false); // leaving without having entered: nothing
  expect(count()).toBe(0);
  setWalkFill(scene, fill, true);
  setWalkFill(scene, fill, true); // entering twice does not double the light
  expect(count()).toBe(1);
  setWalkFill(scene, fill, false);
  expect(count()).toBe(0);
  setWalkFill(scene, fill, false);
  expect(count()).toBe(0);
});
