import { expect, test } from "vitest";
import { frameUsable, PROBE_GRID, probePoints } from "./ao-probe";

test("an all-black frame is unusable, any lit pixel makes it usable", () => {
  const black = new Uint8Array(PROBE_GRID * PROBE_GRID * 4);
  expect(frameUsable(black)).toBe(false);
  const bg = new Uint8Array(black);
  bg.set([30, 30, 34, 255], 40); // the viewer's background colour
  expect(frameUsable(bg)).toBe(true);
  expect(frameUsable(new Uint8Array([0, 0, 0, 255, 7, 7, 7, 255]))).toBe(false);
});

test("probe points cover the frame", () => {
  const p = probePoints();
  expect(p).toHaveLength(PROBE_GRID * PROBE_GRID);
  expect(p.every(([x, y]) => x > 0 && x < 1 && y > 0 && y < 1)).toBe(true);
});
