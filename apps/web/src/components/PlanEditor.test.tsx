import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { addWallOp, applyOps, setWallOp, type EditModel } from "../lib/plan-edit";
import { EditorToolbar, PlanInspector } from "./PlanEditorParts";

const model: EditModel = {
  walls: [{ id: "wall-001", start: [0, 100], end: [8000, 100], thickness: 200, handles: ["A"], provenance: "source_extracted" }],
  openings: [{ id: "opening-001", kind: "door", start: [1000, 100], end: [1900, 100], wall_id: "wall-001", width: 900, height: null, sill: 0, provenance: "source_extracted", handles: ["M"] }],
  rooms: [{ id: "room-001", polygon: [[0, 0], [10, 0], [10, 10]], name: "Room 1", name_source: "defaulted", area: 1, label_point: [5, 2] }],
};
const noop = () => {};
const bar = (o: Partial<Parameters<typeof EditorToolbar>[0]> = {}) =>
  renderToStaticMarkup(<EditorToolbar tool="select" setTool={noop} height="" setHeight={noop} sill="" setSill={noop} thickness="200" setThickness={noop} mode="ortho" setMode={noop} canUndo={false} canRedo={false} onUndo={noop} onRedo={noop} pending={0} busy={false} onSave={noop} onDiscard={noop} {...o} />);

test("toolbar: every tool, the pressed one marked; undo, save and discard wait for a change", () => {
  const html = bar();
  for (const t of ["Select / move", "Add wall", "Add door", "Add window", "Delete"]) expect(html).toContain(t);
  expect(html).toMatch(/aria-pressed="true"[^>]*>Select \/ move/);
  expect(html).toMatch(/<button type="button" disabled="">Undo/);
  expect(html).toMatch(/<button type="button" disabled="">Save/);
  expect(html).toMatch(/<button type="button" disabled="">Discard/);
  const pending = bar({ pending: 2, canUndo: true });
  expect(pending).toContain("Save (2 changes)");
  expect(pending).not.toMatch(/<button type="button" disabled="">Save/);
});

test("door and window tools show height (and a window's sill), empty meaning the project default", () => {
  const w = bar({ tool: "window" });
  expect(w).toContain('aria-label="New opening height"');
  expect(w).toContain('aria-label="New window sill"');
  expect(w).toContain("project default");
  expect(w).toContain("press on a wall and drag along it");
  expect(w).toContain("Press on a wall, drag along it");
  const d = bar({ tool: "door" });
  expect(d).toContain('aria-label="New opening height"');
  expect(d).not.toContain("New window sill");
  expect(bar({ tool: "wall" })).toContain("New wall thickness");
});

const inspector = (sel: Parameters<typeof PlanInspector>[0]["sel"], now: EditModel = model) =>
  renderToStaticMarkup(<PlanInspector base={model} committed={now} now={now} sel={sel} allOps={[]} onOp={noop} />);

test("inspector: nothing selected, then source vs edited columns with the changed field marked", () => {
  expect(inspector(null)).toContain("Select a wall, opening or room");
  const moved = applyOps(model, [setWallOp("e1", model.walls[0], { start: [0, 600], end: [8000, 600] })!]);
  const html = inspector({ kind: "wall", id: "wall-001" }, moved);
  expect(html).toContain("<th>Source</th><th>Edited</th>");
  expect(html).toContain("<td>0, 100</td><td>0, 600 (changed)</td>");
  expect(html).toContain("<td>200</td><td>200</td>"); // thickness untouched
  for (const f of ["Start x (mm)", "End y (mm)", "Thickness (mm)"]) expect(html).toContain(`aria-label="${f}"`);
  expect(html).toContain("Delete wall");
});

test("inspector: opening fields, a new wall has no source, rooms rename", () => {
  const o = inspector({ kind: "opening", id: "opening-001" });
  for (const f of ["Offset on wall (mm)", "Width (mm)", "Height (mm)", "Sill (mm)"]) expect(o).toContain(`aria-label="${f}"`);
  expect(o).toContain("default (set by the server)");
  expect(o).toContain("Delete opening");
  const added = applyOps(model, [addWallOp("e1", [6000, 200], [6000, 4800])!]);
  expect(inspector({ kind: "wall", id: "new-e1" }, added)).toContain("<td>(new)</td>");
  const r = inspector({ kind: "room", id: "room-001" });
  expect(r).toContain('aria-label="Room name"');
  expect(r).toContain('value="Room 1"');
});

test("the angle mode choice shows with the wall tool and select; the inspector gives length and angle fields", () => {
  const w = bar({ tool: "wall" });
  expect(w).toContain('aria-label="Wall angle mode"');
  for (const l of ["Orthogonal", "15° steps", "45° steps", "Free angle"]) expect(w).toContain(l);
  expect(bar({ tool: "door" })).not.toContain('aria-label="Wall angle mode"');
  const html = renderToStaticMarkup(<PlanInspector base={model} committed={model} now={model} sel={{ kind: "wall", id: "wall-001" }} allOps={[]} onOp={noop} />);
  expect(html).toContain('aria-label="Length (mm)"');
  expect(html).toContain('aria-label="Angle (degrees, from +x)"');
});
