import { expect, test } from "vitest";
import { DEFAULT_STEM, isValidStem, resolveStem } from "./model-stem";

test("accepts plain stems", () => {
  for (const s of ["fixture_a", "fixture-b", "A1_b-2"]) expect(isValidStem(s)).toBe(true);
});

test("rejects traversal, separators, dots, empty", () => {
  for (const s of ["", "../x", "a/b", "a\b", "a.b", "a b", "%2e%2e", "a\n"])
    expect(isValidStem(s)).toBe(false);
});

test("resolveStem defaults when absent, null when invalid", () => {
  expect(resolveStem(null)).toBe(DEFAULT_STEM);
  expect(resolveStem("fixture_b")).toBe("fixture_b");
  expect(resolveStem("../secret")).toBeNull();
  expect(resolveStem("")).toBeNull();
});
