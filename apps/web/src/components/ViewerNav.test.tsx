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

test("signed-in project view: one way back per page, through the breadcrumb", () => {
  const h = html(false, m);
  expect(h).not.toContain("Back to");
  expect(h).toContain('href="/projects/p1"');
  expect(h).toContain("Dashboard");
});

test("past version: breadcrumb links to versions, plus a read-only banner", () => {
  const h = html(false, m, 3);
  expect(h).toContain('href="/projects/p1#versions"');
  expect(h).not.toContain("Back to");
  expect(h).toContain("Viewing version 3 (read-only)");
});

test("standalone model goes back to the dashboard through the breadcrumb", () => {
  const h = html(false, null);
  expect(h).not.toContain("Back to");
  expect(h).toContain('aria-label="Breadcrumb"');
});

test("standalone model: not-saved note and Profile link, never on share links", () => {
  const h = renderToStaticMarkup(<ViewerNav shared={false} manifest={null} viewing={null} standalone />);
  expect(h).toContain('role="note"');
  expect(h).toContain("This model is not saved to a project yet.");
  expect(h).toContain('href="/#unsaved"');
  expect(h).toContain(">Save as project<");
  expect(h).toContain('href="/profile"');
  expect(renderToStaticMarkup(<ViewerNav shared manifest={null} viewing={null} standalone />)).toBe("");
});
