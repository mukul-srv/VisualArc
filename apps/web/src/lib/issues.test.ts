import { expect, test } from "vitest";
import { actionOf, focusSelector } from "./issues";
test("fix actions map issue codes to the control to focus", () => {
  expect(actionOf("unmapped_layer")?.kind).toBe("layer");
  expect(focusSelector(actionOf("unmapped_layer")!)).toContain("Layer conventions");
  expect(focusSelector(actionOf("wall_height_missing")!)).toBe("#f-wallHeight");
  expect(focusSelector(actionOf("units_missing")!)).toBe("#f-units");
  expect(actionOf("floor_split_unconfirmed")?.kind).toBe("split");
  expect(actionOf("unpaired_segment")).toBeUndefined();
});
