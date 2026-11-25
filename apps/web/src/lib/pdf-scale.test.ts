import { expect, test } from "vitest";
import { buildPdfBody, EMPTY_PDF_FORM } from "./pdf-scale";

test("a scale is never built without the user's confirmation", () => {
  const r = buildPdfBody({ ...EMPTY_PDF_FORM, ratio: "100" });
  expect(r).toEqual({ ok: false, errors: ["Confirm that the scale is correct."] });
});

test("ratio and two-point scales", () => {
  expect(buildPdfBody({ ...EMPTY_PDF_FORM, ratio: "100", confirmed: true, page: 2 })).toEqual({
    ok: true,
    body: { page: 2, confirmed: true, scale: { kind: "ratio", ratio: 100 } },
  });
  const two = buildPdfBody({ ...EMPTY_PDF_FORM, mode: "two_points", points: ["0", "0", "100", "0"], distance: "3500", confirmed: true });
  expect(two).toMatchObject({ ok: true, body: { scale: { kind: "two_points", p2: [100, 0], distance_mm: 3500 } } });
});

test("bad numbers are listed, not guessed", () => {
  expect(buildPdfBody({ ...EMPTY_PDF_FORM, confirmed: true }).ok).toBe(false);
  expect(buildPdfBody({ ...EMPTY_PDF_FORM, ratio: "-5", confirmed: true }).ok).toBe(false);
  const same = buildPdfBody({ ...EMPTY_PDF_FORM, mode: "two_points", points: ["1", "1", "1", "1"], distance: "10", confirmed: true });
  expect(same).toMatchObject({ ok: false, errors: ["Two points: the points must differ."] });
});
