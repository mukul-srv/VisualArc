import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { Breadcrumbs } from "./Breadcrumbs";

test("trail links every crumb but the current page, and Back goes to the parent", () => {
  const html = renderToStaticMarkup(
    <Breadcrumbs trail={[{ label: "Dashboard", href: "/" }, { label: "House", href: "/projects/p1" }, { label: "Add floor" }]} />,
  );
  expect(html).toContain('aria-label="Breadcrumb"');
  expect(html).toContain('href="/projects/p1"');
  expect(html).toContain("Back to House");
  expect(html).toContain('aria-current="page">Add floor');
  expect(html).not.toContain('href="/projects/p1">Add floor');
});

test("a one-level trail (Dashboard to Profile) goes back to the dashboard; the root renders nothing", () => {
  expect(renderToStaticMarkup(<Breadcrumbs trail={[{ label: "Dashboard", href: "/" }, { label: "Profile" }]} />)).toContain("Back to Dashboard");
  expect(renderToStaticMarkup(<Breadcrumbs trail={[{ label: "Dashboard" }]} />)).toBe("");
});

test("a trail without any link has no Back link", () => {
  const html = renderToStaticMarkup(<Breadcrumbs trail={[{ label: "Shared" }, { label: "House" }]} />);
  expect(html).not.toContain("Back to");
});
