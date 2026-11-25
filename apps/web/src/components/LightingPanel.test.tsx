import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { LightingPanel } from "./LightingPanel";
import type { SiteLighting } from "../lib/site-lighting";

const lightAt = (i: number) => ({ id: `light-${i}`, kind: "point" as const, floor_id: "floor-1", x_mm: 0, y_mm: 0, height_mm: 2400, color: "#ffffff", intensity: 3 });
const site: SiteLighting = { location: { latitude: 51.5, longitude: -0.1 }, north_deg: 20, lights: [{ id: "light-1", kind: "point", floor_id: "floor-1", x_mm: 0, y_mm: 0, height_mm: 2400, color: "#ffffff", intensity: 3 }] };
const render = (canSave: boolean, quality: "medium" | "accuracy" = "medium") =>
  renderToStaticMarkup(
    <LightingPanel quality={quality} onQuality={() => {}} site={site} onSite={() => {}} droppedLights={0} sunInfo="Sun: azimuth 180 deg" canSave={canSave} dirty onSave={() => {}} projectId="p1" planFloors={[{ id: "floor-1", name: "Ground" }]} share={null} selectedId={null} onSelect={() => {}} floorName={() => "Ground"} />,
  );

test("editors can add lights and save; the four quality presets are offered", () => {
  const html = render(true);
  expect(html).toContain("Light plan, square view");
  expect(html).toContain(">Add light source<");
  expect(html).not.toContain("World map");
  expect(html).toContain("Save location, north and lights");
  for (const q of ["Low", "Medium", "High", "Accuracy"]) expect(html).toContain(`>${q}<`);
});

test("viewers can still change quality, but not edit or save the site", () => {
  const html = render(false);
  expect(html).toContain("Light plan, square view");
  expect(html).not.toContain("Add light source"); // read only: no placing
  expect(html).toContain("Read only.");
  expect(html).not.toContain("Save location");
  expect(html).not.toContain("Time of day"); // the sun follows the current date and time
  expect(html).toContain("Sun: azimuth 180 deg");
  expect(html).toMatch(/aria-label="Latitude"[^>]*disabled/);
});

test("accuracy says what it switches off", () => {
  expect(render(true, "accuracy")).toContain("flat look");
});

test("at the cap the add button is disabled and shows 10/10", () => {
  const full = { ...site, lights: Array.from({ length: 10 }, (_, i) => lightAt(i)) };
  const html = renderToStaticMarkup(
    <LightingPanel quality="medium" onQuality={() => {}} site={full} onSite={() => {}} droppedLights={0} sunInfo={null} canSave dirty onSave={() => {}} projectId="p1" planFloors={[{ id: "floor-1", name: "Ground" }]} share={null} selectedId={null} onSelect={() => {}} floorName={() => "Ground"} />,
  );
  expect(html).toMatch(/<button[^>]*disabled[^>]*>Add light source \(10\/10\)</);
  expect(html).toContain("Lights (10/10)");
});

test("a notice says how many saved lights beyond the limit are hidden and will be removed by saving", () => {
  const html = (n: number) =>
    renderToStaticMarkup(
      <LightingPanel quality="medium" onQuality={() => {}} site={site} onSite={() => {}} droppedLights={n} sunInfo={null} canSave dirty onSave={() => {}} projectId="p1" planFloors={[{ id: "floor-1", name: "Ground" }]} share={null} selectedId={null} onSelect={() => {}} floorName={() => "Ground"} />,
    );
  expect(html(3)).toContain("3 saved lights beyond the 10 limit are not shown; saving will remove them.");
  expect(html(1)).toContain("1 saved light beyond the 10 limit is not shown; saving will remove it.");
  expect(html(0)).not.toContain("beyond the 10 limit");
});
