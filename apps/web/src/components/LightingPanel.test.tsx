import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { LightingPanel } from "./LightingPanel";
import type { SiteLighting } from "../lib/site-lighting";

const site: SiteLighting = { location: { latitude: 51.5, longitude: -0.1 }, north_deg: 20, lights: [{ id: "light-1", kind: "point", floor_id: "floor-1", x_mm: 0, y_mm: 0, height_mm: 2400, color: "#ffffff", intensity: 3 }] };
const render = (canSave: boolean, quality: "medium" | "accuracy" = "medium") =>
  renderToStaticMarkup(
    <LightingPanel quality={quality} onQuality={() => {}} site={site} onSite={() => {}} sun={{ date: "2024-06-21", hours: 12, utcOffset: 0, intensity: 1 }} onSun={() => {}} sunInfo="Sun: azimuth 180 deg" canSave={canSave} dirty onSave={() => {}} projectId="p1" planFloors={[{ id: "floor-1", name: "Ground" }]} share={null} selectedId={null} onSelect={() => {}} floorName={() => "Ground"} />,
  );

test("editors can add lights and save; the four quality presets are offered", () => {
  const html = render(true);
  expect(html).toContain("Light plan, square view");
  expect(html).toContain("Click to add a light");
  expect(html).toContain("Save location, north and lights");
  for (const q of ["Low", "Medium", "High", "Accuracy"]) expect(html).toContain(`>${q}<`);
});

test("viewers can still scrub time and change quality, but not edit or save the site", () => {
  const html = render(false);
  expect(html).toContain("Light plan, square view");
  expect(html).not.toContain("Click to add a light"); // read only: no placing
  expect(html).toContain("Read only.");
  expect(html).not.toContain("Save location");
  expect(html).toContain('aria-label="Time of day"');
  expect(html).toContain("Sun: azimuth 180 deg");
  expect(html).toMatch(/aria-label="Latitude"[^>]*disabled/);
});

test("accuracy says what it switches off", () => {
  expect(render(true, "accuracy")).toContain("flat look");
});
