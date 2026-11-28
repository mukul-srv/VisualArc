import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { Issue } from "../lib/api";
import type { DraftResult } from "../lib/jobs";
import { ReviewPanel } from "./ReviewPanel";

const issue = (code: string, severity: Issue["severity"]): Issue => ({ code, severity, message: `msg ${code}`, sources: [] });
const draft = (issues: Issue[], blocking: boolean): DraftResult => ({
  blocking,
  floors: [{ key: null, name: "Ground", issues, stats: { walls: 8, openings: 3, rooms: 2, area: 25_000_000 }, overlay: { unit: "mm", source: { segments: [], total: 0, truncated: false }, model: { walls: [], junctions: [], openings: [], boundaries: [] } } }],
});
const render = (d: DraftResult) => renderToStaticMarkup(<ReviewPanel onClose={() => {}} draft={d} busy={false} onFix={() => {}} onRerun={() => {}} onAccept={() => {}} />);

test("shows stats, the plan canvas and a fix button per actionable issue", () => {
  const html = render(draft([issue("unmapped_layer", "warning")], false));
  expect(html).toContain("8 walls, 3 doors and windows, 2 rooms, 25.0 m² total room area");
  expect(html).toContain("<canvas");
  expect(html).toContain("Map layers");
  expect(html).toContain("Check again");
});

test("accept is disabled while blocking issues remain", () => {
  const blocked = render(draft([issue("units_missing", "blocking")], true));
  expect(blocked).toMatch(/<button disabled=""[^>]*>Create 3D model/);
  expect(blocked).toContain("Choose units");
  expect(render(draft([], false))).not.toMatch(/<button disabled=""[^>]*>Create 3D model/);
});

test("a stale review cannot be accepted", () => {
  const html = renderToStaticMarkup(<ReviewPanel onClose={() => {}} draft={draft([], false)} stale busy={false} onFix={() => {}} onRerun={() => {}} onAccept={() => {}} />);
  expect(html).toMatch(/<button disabled=""[^>]*>Create 3D model/);
  expect(html).toContain("Check again: settings changed");
});

test("the review is a named dialog with a way back to the settings", () => {
  const html = render(draft([], false));
  expect(html).toMatch(/<dialog[^>]*aria-labelledby="review-heading"/);
  expect(html).toContain('id="review-heading"');
  expect(html).toMatch(/<button type="button"[^>]*>Back to settings/);
});
