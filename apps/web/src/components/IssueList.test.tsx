import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { Issue } from "../lib/api";
import { groupIssues, levelOf, summarize, summaryLine } from "../lib/issues";
import { IssueList } from "./IssueList";

const mk = (code: string, severity: Issue["severity"], message = `msg ${code}`): Issue => ({ code, severity, message, sources: [] });

test("errors are visible and open; warnings sit in a collapsed accordion", () => {
  const html = renderToStaticMarkup(<IssueList issues={[mk("unmapped_layer", "warning"), mk("no_walls", "blocking")]} />);
  expect(html).toContain('aria-label="Blocking issues"');
  expect(html).toMatch(/<details open=""[^>]*>[^]*No walls found/); // the error group is open
  const acc = html.slice(html.indexOf('aria-label="Warnings and notes"'));
  expect(acc.startsWith('aria-label="Warnings and notes">')).toBe(true); // accordion itself has no `open`
  expect(acc).toContain("Layers not mapped");
  expect(html.indexOf("Blocking issues")).toBeLessThan(html.indexOf("Warnings and notes"));
});

test("only warnings: no blocking section, still collapsed", () => {
  const html = renderToStaticMarkup(<IssueList issues={[mk("unmapped_layer", "warning")]} />);
  expect(html).not.toContain("Blocking issues");
  expect(html).not.toContain("open=");
});

test("summary line counts issues (not groups) by level", () => {
  const issues = [
    ...Array.from({ length: 23 }, (_, n) => mk("unpaired_segment", "warning", `seg ${n}`)),
    mk("wall_height_defaulted", "warning"),
    mk("elevation_defaulted", "warning"),
    mk("no_walls", "blocking"),
  ];
  const s = summarize(issues);
  expect(s).toEqual({ error: 1, warning: 23, info: 2, total: 26 });
  expect(summaryLine(s)).toBe("1 error, 23 warnings, 2 info");
  expect(summaryLine({ error: 0, warning: 1, info: 0, total: 1 })).toBe("1 warning");
  expect(renderToStaticMarkup(<IssueList issues={issues} />)).toContain("1 error, 23 warnings, 2 info");
});

test("repeated issues fold into one group; nothing is dropped; severity-ordered", () => {
  const issues = [
    mk("wall_height_defaulted", "warning"),
    ...Array.from({ length: 4 }, (_, n) => mk("unpaired_segment", "warning", `seg ${n}`)),
    mk("unmapped_layer", "warning"),
    mk("no_walls", "blocking"),
  ];
  const groups = groupIssues(issues);
  expect(groups.map((g) => [g.code, g.level, g.issues.length])).toEqual([
    ["no_walls", "error", 1],
    ["unpaired_segment", "warning", 4],
    ["unmapped_layer", "warning", 1],
    ["wall_height_defaulted", "info", 1],
  ]);
  expect(groups.flatMap((g) => g.issues)).toHaveLength(issues.length);
  const html = renderToStaticMarkup(<IssueList issues={issues} />);
  for (let n = 0; n < 4; n++) expect(html).toContain(`seg ${n}`); // present, just folded
  expect(html).toContain("Wall lines without a partner (4)");
});

test("known codes get plain-language text; unknown codes fall back without losing the message", () => {
  const html = renderToStaticMarkup(<IssueList issues={[mk("no_walls", "blocking"), mk("brand_new_code", "warning", "raw words")]} />);
  expect(html).toContain("No paired wall lines were recognised");
  expect(html).toContain("Brand new code");
  expect(html).toContain("raw words");
  expect(html).toContain("<code>brand_new_code</code>"); // raw code only inside the group body
  expect(levelOf(mk("anything_defaulted", "warning"))).toBe("info");
  expect(levelOf(mk("anything_defaulted", "blocking"))).toBe("error"); // blocking is never downgraded
});

test("issue sources render as layer:entity_handle inside a collapsed locations list", () => {
  const i = { ...mk("unmapped_layer", "warning"), sources: [{ layer: "WALLS", entity_handle: "1A" }, { layer: "DOORS", entity_handle: "2B" }] };
  const html = renderToStaticMarkup(<IssueList issues={[i]} />);
  expect(html).toContain("2 locations");
  expect(html).toContain("WALLS:1A");
  expect(html).toContain("DOORS:2B");
});

test("issue without sources shows a fallback", () => {
  expect(renderToStaticMarkup(<IssueList issues={[mk("unmapped_layer", "warning")]} />)).toContain("no source entity");
});

test("empty list says so", () => {
  expect(renderToStaticMarkup(<IssueList issues={[]} />)).toContain("No issues found");
});
