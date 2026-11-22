import { expect, test } from "vitest";
import { isDoubleTap } from "./tap";

test("two quick, close taps are a double tap; slow, far or lone ones are not", () => {
  const a = { t: 1000, x: 100, y: 100 };
  expect(isDoubleTap(a, { t: 1200, x: 105, y: 98 })).toBe(true);
  expect(isDoubleTap(a, { t: 1500, x: 100, y: 100 })).toBe(false);
  expect(isDoubleTap(a, { t: 1100, x: 200, y: 100 })).toBe(false);
  expect(isDoubleTap(null, a)).toBe(false);
});
