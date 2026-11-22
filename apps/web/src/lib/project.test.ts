import { expect, test } from "vitest";
import { parseManifest, pickFloor, sortFloors, viewerUrl, type Floor } from "./project";

const g = (c: string) => c.repeat(32);
const floor = (id: string, value: number, c = "a"): Floor => ({
  id,
  name: id,
  elevation: { value, unit: "mm", source: "user_provided" },
  generation_id: g(c),
});

test("sortFloors orders by elevation without mutating", () => {
  const fs = [floor("floor-0", 3000), floor("floor-1", 0), floor("floor-2", -2500)];
  expect(sortFloors(fs).map((f) => f.id)).toEqual(["floor-2", "floor-1", "floor-0"]);
  expect(fs[0].id).toBe("floor-0");
});

test("parseManifest accepts a valid manifest and rejects malformed ones", () => {
  const ok = { id: g("b"), name: "House", floors: [floor("floor-0", 0)] };
  expect(parseManifest(ok)).toEqual(ok);
  expect(parseManifest(null)).toBeNull();
  expect(parseManifest({ ...ok, floors: "x" })).toBeNull();
  expect(parseManifest({ ...ok, floors: [{ ...floor("f", 0), generation_id: "../x" }] })).toBeNull();
  expect(parseManifest({ ...ok, floors: [{ ...floor("f", 0), elevation: { value: 0, source: "guess" } }] })).toBeNull();
});

test("pickFloor: requested floor, else lowest, else null", () => {
  const m = { id: g("b"), name: "H", floors: [floor("floor-0", 3000), floor("floor-1", 0)] };
  expect(pickFloor(m, "floor-0")?.id).toBe("floor-0");
  expect(pickFloor(m, "nope")?.id).toBe("floor-1");
  expect(pickFloor(m, null)?.id).toBe("floor-1");
  expect(pickFloor({ ...m, floors: [] }, null)).toBeNull();
});

test("viewerUrl encodes both ids", () => {
  expect(viewerUrl(g("b"), "floor-1")).toBe(`/viewer?project=${g("b")}&floor=floor-1`);
  expect(viewerUrl("a&b", "c d")).toBe("/viewer?project=a%26b&floor=c%20d");
});

test("viewerUrl appends the share token; parseManifest keeps a valid role", () => {
  expect(viewerUrl(g("b"), undefined, undefined, "t k")).toBe(`/viewer?project=${g("b")}&share=t%20k`);
  const m = { id: "p", name: "n", floors: [], role: "viewer" };
  expect(parseManifest(m)?.role).toBe("viewer");
  expect(parseManifest({ ...m, role: "root" })?.role).toBeUndefined();
});
