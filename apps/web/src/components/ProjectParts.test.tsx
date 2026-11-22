import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { addBlocked } from "./AccessPanel";
import { ProjectList, RecentList } from "./lists";
import { FloorList, ProjectTabs, ProjectToolbar } from "./ProjectParts";
import type { Floor, Role } from "../lib/project";

const id = "a".repeat(32);
const floors: Floor[] = [
  { id: "floor-1", name: "First", elevation: { value: 3000, unit: "mm", source: "user_provided" }, generation_id: "b".repeat(32) },
  { id: "floor-0", name: "Ground", elevation: { value: 0, unit: "mm", source: "user_provided" }, generation_id: "c".repeat(32) },
];
const toolbar = (role: Role, f = floors) =>
  renderToStaticMarkup(<ProjectToolbar id={id} role={role} floors={f} onShare={() => {}} onRename={() => {}} onDelete={() => {}} />);

test("toolbar: each role gets its own set of actions", () => {
  const owner = toolbar("owner");
  for (const t of ["Open in viewer", "Add floor", ">Share<", ">Rename<", ">Delete<"]) expect(owner).toContain(t);
  expect(owner).toContain(`/viewer?project=${id}&amp;floor=floor-0`); // lowest floor
  expect(owner).toContain(`/new?project=${id}`);
  const editor = toolbar("editor");
  expect(editor).toContain("Add floor");
  expect(editor).toContain(">Rename<");
  expect(editor).not.toMatch(/>Share<|>Delete</);
  const viewer = toolbar("viewer");
  expect(viewer).toContain("Open in viewer");
  expect(viewer).not.toMatch(/Add floor|>Rename<|>Share<|>Delete</);
});

test("toolbar: no floors disables Open with a reason", () => {
  const html = toolbar("owner", []);
  expect(html).toContain("no floors yet");
  expect(html).toContain('title="Add a floor first"');
  expect(html).not.toContain("/viewer?project");
});

test("tabs: Sharing is one click for the owner only", () => {
  const tabs = (role: Role) => renderToStaticMarkup(<ProjectTabs role={role} tab="floors" onSelect={() => {}} />);
  expect(tabs("owner")).toContain(">Sharing<");
  for (const r of ["editor", "viewer"] as Role[]) {
    const html = tabs(r);
    expect(html).not.toContain("Sharing");
    for (const t of ["Floors", "Conventions", "Versions"]) expect(html).toContain(t);
  }
});

test("floor list: rename/remove for editors and owners, sorted by elevation", () => {
  const list = (role: Role) =>
    renderToStaticMarkup(<FloorList projectId={id} floors={floors} role={role} onRename={() => {}} onRemove={() => {}} />);
  const owner = list("owner");
  expect(owner.indexOf("Ground")).toBeLessThan(owner.indexOf("First"));
  expect(owner.match(/>Rename</g)).toHaveLength(2);
  expect(owner.match(/>Remove</g)).toHaveLength(2);
  expect(list("editor")).toContain(">Remove<");
  expect(list("viewer")).not.toMatch(/>Rename<|>Remove</);
  expect(renderToStaticMarkup(<FloorList projectId={id} floors={[]} role="editor" onRename={() => {}} onRemove={() => {}} />)).toContain("Add the first floor");
  expect(renderToStaticMarkup(<FloorList projectId={id} floors={[]} role="viewer" onRename={() => {}} onRemove={() => {}} />)).not.toContain("Add the first floor");
});

const summary = { id, name: "House", floor_count: 2, version: 3, updated_at: "2026-05-01T10:20:30+00:00", thumbnail: null };

test("dashboard rows: visible actions by role", () => {
  const rows = (role: string, floor_count = 2) =>
    renderToStaticMarkup(<ProjectList projects={[{ ...summary, role, floor_count }]} onDelete={() => {}} />);
  const owner = rows("owner");
  expect(owner).toContain(`href="/viewer?project=${id}"`);
  expect(owner).toContain(`/new?project=${id}`);
  expect(owner).toContain(`/projects/${id}#sharing`);
  expect(owner).toContain('aria-label="Delete House"');
  const editor = rows("editor");
  expect(editor).toContain("Add floor");
  expect(editor).not.toMatch(/>Share<|>Delete</);
  expect(editor).toContain("(shared: editor)");
  const viewer = rows("viewer");
  expect(viewer).toContain(">Open<");
  expect(viewer).not.toMatch(/Add floor|>Share<|>Delete</);
  expect(rows("owner", 0)).toContain("Open (no floors)");
});

test("recent list: a standalone model is labelled and can be saved as a project", () => {
  const g = { name: null, generation_id: "d".repeat(32), created_at: "2026-05-01T10:20:30+00:00", project_id: null, project_name: null, floor_id: null, floor_name: null };
  const html = renderToStaticMarkup(<RecentList items={[g]} onSave={() => {}} />);
  expect(html).toContain("Standalone model");
  expect(html).toContain("Save as project");
  expect(renderToStaticMarkup(<RecentList items={[{ ...g, project_id: id, project_name: "House", floor_id: "floor-0", floor_name: "Ground" }]} onSave={() => {}} />)).not.toContain("Standalone");
});

test("recent list: the name is the uploaded file name, with rename and delete only for standalone models and a tooltip", () => {
  const g = { name: "Villa plan.dxf", generation_id: "e".repeat(32), created_at: "2026-05-01T10:20:30+00:00", project_id: null, project_name: null, floor_id: null, floor_name: null };
  const html = renderToStaticMarkup(<RecentList items={[g]} onRename={() => {}} onDelete={() => {}} />);
  expect(html).toContain("Villa plan.dxf");
  expect(html).not.toContain("Model eeeeeeee"); // the file name, not the id, when there is one
  expect(html).toMatch(/title="[^"]*cannot be shared[^"]*"/); // hover explanation on the label
  expect(html).toContain('aria-label="Rename Villa plan.dxf"');
  expect(html).toContain('aria-label="Delete Villa plan.dxf"');
  expect(renderToStaticMarkup(<RecentList items={[{ ...g, name: null }]} />)).toContain("Model eeeeeeee"); // no name: short id
  const inProject = { ...g, project_id: id, project_name: "House", floor_id: "floor-0", floor_name: "Ground" };
  const projectHtml = renderToStaticMarkup(<RecentList items={[inProject]} onRename={() => {}} onDelete={() => {}} />);
  expect(projectHtml).toContain("House / Ground");
  expect(projectHtml).not.toMatch(/Rename|Delete/); // those are changed through the project
});

test("sharing cap: a new email is blocked at the cap, a role change is not", () => {
  const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ user_id: `u${i}`, email: `p${i}@x.io`, display_name: "p", role: "viewer" as const }));
  const full = { collaborators: rows(6), invites: [{ email: "i1@x.io", role: "viewer" as const }, { email: "i2@x.io", role: "editor" as const }], link_token: null, max_collaborators: 8 };
  expect(addBlocked(full, "new@x.io")).toBe("Limit of 8 collaborators reached. Remove someone to invite more.");
  expect(addBlocked(full, " P0@X.io ")).toBeNull();
  expect(addBlocked(full, "i2@x.io")).toBeNull();
  expect(addBlocked({ ...full, collaborators: rows(5) }, "new@x.io")).toBeNull();
});

test("a missing role fails closed to viewer", () => {
  const html = renderToStaticMarkup(<ProjectList projects={[{ ...summary, role: undefined }]} onDelete={() => {}} />);
  expect(html).not.toMatch(/Add floor|>Share<|>Delete</);
  expect(html).toContain("(shared: viewer)");
});
