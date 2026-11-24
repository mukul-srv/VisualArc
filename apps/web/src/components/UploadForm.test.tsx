import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { Preflight, Presets } from "../lib/api";
import type { FormValues } from "../lib/params";
import { initialRows } from "../lib/split";
import { UploadForm } from "./UploadForm";

const presets: Presets = {
  residential: { wall_height: 2700, ceiling_height: 2700, door_height: 2100, window_height: 1200, window_sill: 900, floor_to_floor: 3000 },
  commercial: { wall_height: 3000, ceiling_height: 2700, door_height: 2100, window_height: 1500, window_sill: 900, floor_to_floor: 3600 },
};
const form: FormValues = { buildingType: "residential", wallHeight: "", ceilingHeight: "", units: "", doorHeight: "", windowHeight: "", windowSill: "" };
const cands = [0, 1].map((n) => ({
  key: `L${n}`,
  bbox: { min: [0, 0] as [number, number], max: [5000, 4000] as [number, number] },
  entity_counts: {},
  proposed_offset: { x: 0, y: 0, source: "inferred" as const },
}));
const pre = (o: Partial<Preflight> = {}): Preflight => ({ upload_id: "u", issues: [], needs: [], inventory: { layers: [], entity_counts: {} }, ...o });

const render = (p: Preflight, f: FormValues = form, over: { exclude?: number; target?: string } = {}) =>
  renderToStaticMarkup(
    <UploadForm
      pre={p}
      form={f}
      setForm={() => {}}
      presets={presets}
      rows={initialRows(p.floor_candidates ?? []).map((r, i) => ({ ...r, exclude: i === over.exclude }))}
      setRow={() => {}}
      projectName=""
      setProjectName={() => {}}
      proj={{ on: over.target !== undefined, target: over.target ?? "", floorName: "", elevation: "" }}
      setProj={() => {}}
      errors={[]}
      disabled={false}
      onSubmit={() => {}}
    />,
  );
// everything outside the Advanced <details> is what a normal user sees
const general = (html: string) => html.replace(/<details[\s\S]*<\/details>/, "");

test("General shows only essentials: building type (Residential preselected) and the button", () => {
  const g = general(render(pre()));
  expect(g.match(/<input[^>]*value="residential"[^>]*>/)?.[0]).toContain("checked");
  expect(g.match(/<input[^>]*value="commercial"[^>]*>/)?.[0]).not.toContain("checked");
  expect(g).toContain('value="commercial"');
  expect(g).toContain("Review");
  expect(g).not.toMatch(/Wall height|Ceiling height|Door height|Window|elevation|Offset|Add to a project|<select/i);
});

test("units question appears in General only when the DXF lacks units", () => {
  expect(general(render(pre()))).not.toContain("What unit was this drawing made in?");
  const g = general(render(pre({ needs: ["units"] })));
  expect(g).toContain("What unit was this drawing made in?");
  expect(g).toContain("<select");
});

test("Advanced is collapsed by default and holds the expert controls with preset placeholders", () => {
  const html = render(pre());
  expect(html).toContain("<details");
  expect(html).not.toMatch(/<details[^>]*\bopen\b/);
  expect(html).toContain("Advanced settings");
  for (const label of ["Wall height", "Ceiling height", "Door height", "Window height", "Window sill", "Add to a project"]) {
    expect(html).toContain(label);
    expect(general(html)).not.toContain(label);
  }
  expect(html).toContain('placeholder="default 2700"');
  expect(render(pre(), { ...form, buildingType: "commercial" })).toContain('placeholder="default 3000"');
});

test("split: floor list shows Build + Name only in General; elevation and offsets are Advanced", () => {
  const html = render(pre({ floor_candidates: cands }));
  const g = general(html);
  expect(g).toContain("Build L0");
  expect(g).toContain("Name L0");
  expect(g).toContain("Project name");
  expect(g).not.toMatch(/Elevation|Offset/);
  expect(html).toContain("Elevation L1");
  expect(html).toContain("Offset X L1");
  expect(html).toContain('placeholder="default 3000"'); // second floor: order index 1 x residential 3000
});

test("an excluded floor row has no elevation placeholder", () => {
  const html = render(pre({ floor_candidates: cands }), form, { exclude: 0 });
  expect(html.match(/<input[^>]*aria-label="Elevation L0"[^>]*>/)?.[0]).not.toContain("placeholder");
  expect(html.match(/<input[^>]*aria-label="Elevation L1"[^>]*>/)?.[0]).toContain('placeholder="default 0"'); // first kept floor
});

test("project elevation placeholder: first floor of a new project says default 0", () => {
  expect(render(pre(), form, { target: "New house" })).toContain('placeholder="default 0"');
  expect(render(pre(), form, { target: "a".repeat(32) })).toContain('placeholder="default highest floor + 3000"');
});
