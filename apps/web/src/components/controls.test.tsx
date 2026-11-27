import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";
import { visibleControls } from "../lib/controls";
import { AppNav } from "./AppNav";
import { FloorList, ProjectTabs, ProjectToolbar } from "./ProjectParts";
import { ProjectList, RecentList } from "./lists";
import { ConventionsPanel } from "./ConventionsPanel";
import { UploadForm } from "./UploadForm";
import { ViewerToolbar } from "./ViewerToolbar";
import { Hint } from "./Hint";
import { EMPTY_FORM, NO_TARGET } from "../lib/upload-state";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: () => {} }) }));

const id = "a".repeat(32);
const floors = [
  { id: "floor-0", name: "Ground", elevation: { value: 0, unit: "mm", source: "user_provided" as const }, generation_id: "b".repeat(32) },
  { id: "floor-1", name: "First", elevation: { value: 3000, unit: "mm", source: "user_provided" as const }, generation_id: "c".repeat(32) },
];
const project = { id, role: "owner", name: "House", floor_count: 2, version: 3, updated_at: "2026-05-01T10:20:30+00:00", thumbnail: null };
const standalone = { name: "Villa.dxf", generation_id: "d".repeat(32), created_at: "2026-05-01T10:20:30+00:00", project_id: null, project_name: null, floor_id: null, floor_name: null };

test("the counter ignores closed details but keeps their summary", () => {
  expect(visibleControls('<a href="/">x</a><details><summary>More</summary><button>a</button><button>b</button></details>')).toBe(2);
  expect(visibleControls('<details open=""><summary>S</summary><button>a</button></details>')).toBe(2);
});

// Controls visible at first glance per screen (owner), counted without the bodies of closed folds.
// Before the simplification: nav 4, project row 5, recent row 4, project toolbar 5, tabs 5, floor list 6
// (2 floors), upload form 4, conventions panel 1 + one select per unmapped layer, viewer toolbar 4 (now 3).
// projectToolbar 3 -> 4: UX spec makes the owner Share action a visible toolbar button (was inside More).
// Kept as upper bounds so the screens do not grow back; every control still exists, one click away.
const MAX = { nav: 3, projectRow: 3, recentRow: 3, projectToolbar: 4, projectTabs: 4, uploadForm: 4, conventions: 1, viewerToolbar: 3, floorList: 4 };

test("first-glance control counts stay low", () => {
  const counts = {
    nav: visibleControls(renderToStaticMarkup(<AppNav />)),
    projectRow: visibleControls(renderToStaticMarkup(<ProjectList projects={[project]} onDelete={() => {}} />)),
    recentRow: visibleControls(renderToStaticMarkup(<RecentList items={[standalone]} onSave={() => {}} onRename={() => {}} onDelete={() => {}} />)),
    projectToolbar: visibleControls(renderToStaticMarkup(<ProjectToolbar id={id} role="owner" floors={floors} onShare={() => {}} onRename={() => {}} onDelete={() => {}} />)),
    projectTabs: visibleControls(renderToStaticMarkup(<ProjectTabs role="owner" tab="floors" onSelect={() => {}} />)),
    uploadForm: visibleControls(renderToStaticMarkup(<UploadForm pre={{ upload_id: id, needs: [], inventory: { layers: [], entity_counts: {} }, issues: [] } as never} form={EMPTY_FORM} setForm={() => {}} presets={null} rows={[]} setRow={() => {}} projectName="" setProjectName={() => {}} proj={NO_TARGET} setProj={() => {}} errors={[]} disabled={false} onSubmit={() => {}} />)),
    conventions: visibleControls(renderToStaticMarkup(<ConventionsPanel spec={{ preset: "aia", mapping: {} }} setSpec={() => {}} presets={[{ id: "aia", label: "AIA", source: "s", layers: {} }]} roles={["wall", "floor"]} layers={[]} />)),
    viewerToolbar: visibleControls(renderToStaticMarkup(<ViewerToolbar walking={false} top={false} measuring={false} roofPresent roofOn onWalk={() => {}} onRoof={() => {}} onTop={() => {}} onMeasure={() => {}} />)),
    floorList: visibleControls(renderToStaticMarkup(<FloorList projectId={id} floors={floors} role="owner" onRename={() => {}} onRemove={() => {}} />)),
  };
  process.stdout.write(`CONTROLS ${JSON.stringify(counts)}
`);
  for (const [k, v] of Object.entries(counts)) expect(v, k).toBeLessThanOrEqual(MAX[k as keyof typeof MAX]);
});

test("nothing was removed: every moved action is still in the markup, behind its menu", () => {
  const row = renderToStaticMarkup(<ProjectList projects={[project]} onDelete={() => {}} />);
  for (const t of ["Open", "Add floor", "Share", "Delete"]) expect(row).toContain(t);
  const toolbar = renderToStaticMarkup(<ProjectToolbar id={id} role="owner" floors={floors} onShare={() => {}} onRename={() => {}} onDelete={() => {}} />);
  for (const t of ["Open in viewer", "Add floor", "Share", "Rename", "Delete"]) expect(toolbar).toContain(t);
  const viewer = renderToStaticMarkup(<ViewerToolbar walking={false} top={false} measuring={false} roofPresent roofOn onWalk={() => {}} onRoof={() => {}} onTop={() => {}} onMeasure={() => {}} />);
  for (const t of ["Walk", "Roof", "Top-down", "Measure"]) expect(viewer).toContain(t);
  expect(viewer).not.toMatch(/Reset view|Full screen/);
  expect(renderToStaticMarkup(<AppNav />)).toMatch(/Profile[\s\S]*Log out/);
});

test("tool labels never change; the state is aria-pressed", () => {
  const on = renderToStaticMarkup(<ViewerToolbar walking top measuring roofPresent roofOn onWalk={() => {}} onRoof={() => {}} onTop={() => {}} onMeasure={() => {}} />);
  const off = renderToStaticMarkup(<ViewerToolbar walking={false} top={false} measuring={false} roofPresent roofOn={false} onWalk={() => {}} onRoof={() => {}} onTop={() => {}} onMeasure={() => {}} />);
  for (const label of [">Walk<", ">Roof<", ">Top-down<", ">Measure<"]) expect([on, off].every((h) => h.includes(label))).toBe(true);
  expect(on).toContain('aria-pressed="true"');
  expect(off).toContain('aria-pressed="false"');
  expect(on).not.toMatch(/Exit walk|Roof: o|Perspective/);
});

test("a hint is visible text linked to its mark (hover and keyboard focus), not only a title", () => {
  const html = renderToStaticMarkup(<Hint text="What this does" />);
  const id = /aria-describedby="([^"]+)"/.exec(html)![1];
  expect(html).toContain(`id="${id}"`);
  expect(html).toContain("What this does");
  expect(html).toContain('tabindex="0"'); // reachable by keyboard
});

test("viewer toolbar offers OBJ and IFC export only when the model has an API source", () => {
  const props = { walking: false, top: false, measuring: false, roofPresent: false, roofOn: false, onWalk: () => {}, onRoof: () => {}, onTop: () => {}, onMeasure: () => {} };
  expect(renderToStaticMarkup(<ViewerToolbar {...props} />)).not.toContain("Export");
  const html = renderToStaticMarkup(<ViewerToolbar {...props} exports={{ obj: "/x/obj", ifc: "/x/ifc" }} />);
  expect(html).toContain('href="/x/obj"');
  expect(html).toContain("Export IFC");
});
