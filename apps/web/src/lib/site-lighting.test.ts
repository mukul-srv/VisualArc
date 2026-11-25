import { expect, test, vi } from "vitest";
import { mapClickToLatLon, nextLightId, NO_LIGHTING, parseLighting, putLighting, type ArtificialLight } from "./site-lighting";

const light = (id: string): ArtificialLight => ({ id, kind: "point", floor_id: "floor-1", x_mm: 1, y_mm: 2, height_mm: 2400, color: "#ffffff", intensity: 2 });

test("parseLighting keeps valid parts and drops malformed ones", () => {
  expect(parseLighting(undefined)).toEqual(NO_LIGHTING);
  const got = parseLighting({ location: { latitude: 95, longitude: 0 }, north_deg: -90, lights: [light("a"), { ...light("b"), color: "red" }, { ...light("c"), kind: "laser" }, { ...light("d"), intensity: 50 }, { ...light("e"), intensity: -2 }] });
  expect(got.location).toBeNull();
  expect(got.north_deg).toBe(270);
  expect(got.lights.map((l) => [l.id, l.intensity])).toEqual([["a", 2], ["d", 10], ["e", 0]]); // out-of-range intensity is clamped, not dropped
  expect(parseLighting({ location: { latitude: 51.5, longitude: -0.1 } }).location).toEqual({ latitude: 51.5, longitude: -0.1 });
});

test("nextLightId skips used ids", () => {
  expect(nextLightId([])).toBe("light-1");
  expect(nextLightId([light("light-1"), light("light-3")])).toBe("light-2");
});

test("putLighting sends the whole setting", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({ lighting: NO_LIGHTING, version: 4 })));
  const body = { location: { latitude: 10, longitude: 20 }, north_deg: 45, lights: [light("a")] };
  expect((await putLighting("p1", body, f as unknown as typeof fetch)).ok).toBe(true);
  const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/v1/projects/p1/lighting");
  expect(init.method).toBe("PUT");
  expect(JSON.parse(init.body as string)).toEqual(body);
});

test("a click on the world map maps to latitude and longitude", () => {
  expect(mapClickToLatLon(0.5, 0.5)).toEqual({ latitude: 0, longitude: 0 });
  expect(mapClickToLatLon(0, 0)).toEqual({ latitude: 90, longitude: -180 });
  expect(mapClickToLatLon(1, 1)).toEqual({ latitude: -90, longitude: 180 });
  expect(mapClickToLatLon(2, -1)).toEqual({ latitude: 90, longitude: 180 }); // clamped
});
