import { expect, test } from "vitest";
import { arrowStep, canPlace, clampTo, clickToPlan, moveLight, nudgeLight, placeLight, planToScreen, setLightCoord, squareBounds, squareFit } from "./light-plan";
import { MAX_LIGHTS, type ArtificialLight } from "./site-lighting";

const sq = squareBounds({ minX: 0, minY: 0, maxX: 10000, maxY: 4000 });
const light = (id: string, x = 1000, y = 1000): ArtificialLight => ({ id, kind: "point", floor_id: "f1", x_mm: x, y_mm: y, height_mm: 2400, color: "#ffffff", intensity: 3 });

test("the plan square is equal-aspect with a margin and centred on the drawing", () => {
  expect(sq.maxX - sq.minX).toBeCloseTo(sq.maxY - sq.minY);
  expect(sq.maxX - sq.minX).toBeCloseTo(10000 * 1.16);
  expect((sq.minX + sq.maxX) / 2).toBe(5000);
  expect((sq.minY + sq.maxY) / 2).toBe(2000);
  expect(squareBounds(null).maxX).toBe(10000);
});

test("click <-> plan mm round trip, with and without a floor offset", () => {
  const f = squareFit(sq, 300);
  for (const off of [[0, 0], [2500, -1200]] as [number, number][]) {
    for (const [x, y] of [[0, 0], [5000, 2000], [9999, 3999], [-300, 4200]]) {
      const [sx, sy] = planToScreen(f, x, y, off);
      const [bx, by] = clickToPlan(f, sx, sy, off);
      expect(Math.abs(bx - x)).toBeLessThanOrEqual(1); // rounded to a whole mm
      expect(Math.abs(by - y)).toBeLessThanOrEqual(1);
    }
  }
  // plan up is screen up: a higher y is a smaller screen y
  expect(planToScreen(f, 0, 3000)[1]).toBeLessThan(planToScreen(f, 0, 1000)[1]);
  // the square's corners map to its bounds
  const [x0, y0] = clickToPlan(f, 0, 300);
  expect([x0, y0]).toEqual([Math.round(sq.minX), Math.round(sq.minY)]);
});

test("place, drag and nudge stay inside the square", () => {
  const placed = placeLight([], "f1", 1e6, -1e6, sq, true);
  expect(placed.id).toBe("light-1");
  expect(placed.lights[0]).toMatchObject({ floor_id: "f1", x_mm: Math.round(sq.maxX), y_mm: Math.round(sq.minY), height_mm: 2400 });
  expect(clampTo(sq, 5000, 2000)).toEqual([5000, 2000]);
  const moved = moveLight([light("a")], "a", -1e9, 1e9, sq, true);
  expect([moved[0].x_mm, moved[0].y_mm]).toEqual([Math.round(sq.minX), Math.round(sq.maxY)]);
  const edge = [light("a", Math.round(sq.maxX), 1000)];
  expect(nudgeLight(edge, "a", 500, 0, sq, true)[0].x_mm).toBe(Math.round(sq.maxX)); // cannot leave
  expect(nudgeLight([light("a")], "a", 100, -100, sq, true)[0]).toMatchObject({ x_mm: 1100, y_mm: 900 });
});

test("viewers cannot place, move or nudge; the cap holds", () => {
  const ls = [light("a")];
  expect(placeLight(ls, "f1", 10, 10, sq, false)).toEqual({ lights: ls, id: null });
  expect(moveLight(ls, "a", 5, 5, sq, false)).toBe(ls);
  expect(nudgeLight(ls, "a", 100, 0, sq, false)).toBe(ls);
  expect(canPlace(false, 0)).toBe(false);
  expect(canPlace(true, MAX_LIGHTS)).toBe(false);
  expect(canPlace(true, MAX_LIGHTS - 1)).toBe(true);
  expect(moveLight(ls, "nope", 5, 5, sq, true)).toBe(ls);
});

test("arrow keys step 100 mm (500 with shift), plan up is +y", () => {
  expect(arrowStep("ArrowUp", false)).toEqual([0, 100]);
  expect(arrowStep("ArrowLeft", true)).toEqual([-500, 0]);
  expect(arrowStep("a", false)).toBeNull();
});

test("Add light source: a new light at the centre of the plan square, selected by its id", () => {
  const cx = (sq.minX + sq.maxX) / 2, cy = (sq.minY + sq.maxY) / 2;
  const r = placeLight([light("a")], "f2", cx, cy, sq, true);
  expect(r.id).toBe("light-1");
  expect(r.lights.at(-1)).toMatchObject({ floor_id: "f2", x_mm: Math.round(cx), y_mm: Math.round(cy) });
  // the centre is inside the square, so it is visible at once
  const f = squareFit(sq, 300);
  const [sx, sy] = planToScreen(f, cx, cy);
  expect(sx).toBeGreaterThan(0);
  expect(sx).toBeLessThan(300);
  expect(sy).toBeGreaterThan(0);
  expect(sy).toBeLessThan(300);
  // the tenth light is allowed, the eleventh is not
  const nine = Array.from({ length: 9 }, (_, i) => light(`l${i}`));
  expect(placeLight(nine, "f1", cx, cy, sq, true).lights).toHaveLength(10);
  expect(placeLight([...nine, light("l9")], "f1", cx, cy, sq, true).id).toBeNull();
});

test("typed x/y are clamped to the plan square like a drag; junk and viewers change nothing", () => {
  const ls = [light("a", 1000, 1000)];
  const x = setLightCoord(ls, "a", "x", "9999999", sq, true); // the API would allow 1e7
  expect([x[0].x_mm, x[0].y_mm]).toEqual([Math.round(sq.maxX), 1000]);
  const y = setLightCoord(ls, "a", "y", "-9999999", sq, true);
  expect([y[0].x_mm, y[0].y_mm]).toEqual([1000, Math.round(sq.minY)]);
  expect(setLightCoord(ls, "a", "x", "2500", sq, true)[0].x_mm).toBe(2500);
  expect(setLightCoord(ls, "a", "x", "", sq, true)).toBe(ls);
  expect(setLightCoord(ls, "a", "x", "abc", sq, true)).toBe(ls);
  expect(setLightCoord(ls, "a", "x", "5", sq, false)).toBe(ls);
});
