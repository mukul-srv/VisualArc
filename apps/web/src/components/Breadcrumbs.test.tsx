import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { Breadcrumbs } from "./Breadcrumbs";

test("trail links every crumb but the current page (the parent crumb is the way back)", () => {
  const html = renderToStaticMarkup(
    <Breadcrumbs trail={[{ label: "Dashboard", href: "/" }, { label: "House", href: "/projects/p1" }, { label: "Add floor" }]} />,
  );
  expect(html).toContain('aria-label="Breadcrumb"');
  expect(html).toContain('href="/projects/p1"');
  expect(html).not.toContain("Back to");
  expect(html).toContain('aria-current="page">Add floor');
  expect(html).not.toContain('href="/projects/p1">Add floor');
});

test("a one-level trail (Dashboard to Profile) links the dashboard once; the root renders nothing", () => {
  const html = renderToStaticMarkup(<Breadcrumbs trail={[{ label: "Dashboard", href: "/" }, { label: "Profile" }]} />);
  expect(html.match(/href="\/"/g)).toHaveLength(1);
  expect(renderToStaticMarkup(<Breadcrumbs trail={[{ label: "Dashboard" }]} />)).toBe("");
});

test("a trail without any link has no Back link", () => {
  const html = renderToStaticMarkup(<Breadcrumbs trail={[{ label: "Shared" }, { label: "House" }]} />);
  expect(html).not.toContain("Back to");
});
