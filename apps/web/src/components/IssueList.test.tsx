import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { Issue } from "../lib/api";
import { IssueList } from "./IssueList";

const mk = (code: string, severity: Issue["severity"]): Issue => ({
  code,
  severity,
  message: `msg ${code}`,
  sources: [],
});

test("blocking and warnings render in separate labelled sections", () => {
  const html = renderToStaticMarkup(<IssueList issues={[mk("a", "warning"), mk("b", "blocking")]} />);
  expect(html).toContain('aria-label="Blocking issues"');
  expect(html).toContain('aria-label="Warnings"');
  expect(html).toMatch(/BLOCKING<\/strong> <code>b<\/code>/);
  expect(html.indexOf("Blocking issues")).toBeLessThan(html.indexOf("Warnings"));
});

test("only warnings: no blocking section", () => {
  const html = renderToStaticMarkup(<IssueList issues={[mk("a", "warning")]} />);
  expect(html).not.toContain("Blocking issues");
});

test("empty list says so", () => {
  expect(renderToStaticMarkup(<IssueList issues={[]} />)).toContain("No issues found");
});
