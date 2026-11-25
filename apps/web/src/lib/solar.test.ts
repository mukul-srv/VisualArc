import { expect, test } from "vitest";
import { daylight, defaultUtcOffset, localToUtcMs, sunDirection, sunPosition } from "./solar";

const utc = (s: string) => Date.parse(s);

test("equinox noon on the equator: sun almost overhead", () => {
  const p = sunPosition(0, 0, utc("2024-03-20T12:07:30Z"));
  expect(p.elevation).toBeGreaterThan(89.5); // solar noon is 12:07 UTC (equation of time -7.5 min)
});

test("London summer solstice noon: elevation 90 - lat + 23.44, due south", () => {
  const p = sunPosition(51.5, 0, utc("2024-06-21T12:02:00Z"));
  expect(p.elevation).toBeCloseTo(90 - 51.5 + 23.44, 0);
  expect(p.azimuth).toBeCloseTo(180, 0);
});

test("London winter solstice noon: low sun; midnight: below the horizon", () => {
  expect(sunPosition(51.5, 0, utc("2024-12-21T11:59:00Z")).elevation).toBeCloseTo(90 - 51.5 - 23.44, 0);
  expect(sunPosition(51.5, 0, utc("2024-06-21T00:00:00Z")).elevation).toBeLessThan(0);
});

test("morning sun is in the east, afternoon in the west, southern hemisphere faces north", () => {
  expect(sunPosition(40, 0, utc("2024-03-20T07:00:00Z")).azimuth).toBeLessThan(120);
  expect(sunPosition(40, 0, utc("2024-03-20T07:00:00Z")).azimuth).toBeGreaterThan(60);
  expect(sunPosition(40, 0, utc("2024-03-20T17:00:00Z")).azimuth).toBeGreaterThan(240);
  const s = sunPosition(-33.9, 151.2, utc("2024-06-21T02:10:00Z")); // Sydney local noon
  expect(Math.min(s.azimuth, 360 - s.azimuth)).toBeLessThan(5);
  expect(s.elevation).toBeCloseTo(90 - 33.9 - 23.44, 0);
});

test("local time to UTC and default offset", () => {
  expect(localToUtcMs("2024-06-21", 14, 2)).toBe(utc("2024-06-21T12:00:00Z"));
  expect(defaultUtcOffset(-74)).toBe(-5);
  expect(defaultUtcOffset(151.2)).toBe(10);
});

test("sun direction follows the north angle (plan +Y is -Z in the viewer)", () => {
  const [x, y, z] = sunDirection(0, 0, 0); // sun in the north, north = plan +Y
  expect([x, y, z].map((v) => Math.round(v * 1e6) / 1e6)).toEqual([0, 0, -1]);
  const [x2, , z2] = sunDirection(90, 0, 90); // east sun, plan rotated so north is plan east: due plan +Y again
  expect([x2, z2].map((v) => Math.round(v * 1e6) / 1e6)).toEqual([0, -1]);
  expect(sunDirection(90, 30, 0)[0]).toBeGreaterThan(0.8); // east = +X
});

test("daylight: sun off below the horizon, full high up, sky never black", () => {
  expect(daylight(-5).sun).toBe(0);
  expect(daylight(45).sun).toBe(1);
  expect(daylight(-30).sky).toBeCloseTo(0.15);
  expect(daylight(30).sky).toBe(1);
});
