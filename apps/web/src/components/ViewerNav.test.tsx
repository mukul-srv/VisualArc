import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { ViewerNav } from "./ViewerNav";

const m = { id: "p1", name: "House" };
const html = (shared: boolean | null, manifest: typeof m | null, viewing: number | null = null) =>
  renderToStaticMarkup(<ViewerNav shared={shared} manifest={manifest} viewing={viewing} />);

test("until the share state is known nothing account-related renders (server render, first frame)", () => {
  for (const manifest of [m, null]) expect(html(null, manifest)).toBe("");
});

test("share-link visitors get only the read-only label, never account links", () => {
  const h = html(true, m);
  expect(h).toContain("Shared view (read-only): House");
  expect(h).not.toMatch(/href=|Back to|Dashboard/);
  expect(html(true, null)).toBe("");
});

test("signed-in project view: back to project, breadcrumb to the dashboard", () => {
  const h = html(false, m);
  expect(h).toContain("Back to project");
  expect(h).toContain('href="/projects/p1"');
  expect(h).toContain("Dashboard");
});

test("past version: back to versions and a read-only banner", () => {
  const h = html(false, m, 3);
  expect(h).toContain('href="/projects/p1#versions"');
  expect(h).toContain("Back to versions");
  expect(h).toContain("Viewing version 3 (read-only)");
});

test("standalone model goes back to the dashboard", () => {
  expect(html(false, null)).toContain("Back to dashboard");
});
