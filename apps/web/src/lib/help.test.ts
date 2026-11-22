import { expect, test } from "vitest";
import { HELP, PARAM_HELP } from "./help";
import { PARAM_LABEL } from "./parameters";

test("every project parameter has a plain-language hint", () => {
  for (const k of Object.keys(PARAM_LABEL)) expect(PARAM_HELP[k], k).toBeTruthy();
});

test("hints are short sentences, not paragraphs", () => {
  for (const t of [...Object.values(HELP), ...Object.values(PARAM_HELP)]) expect(t.length).toBeLessThan(200);
});
