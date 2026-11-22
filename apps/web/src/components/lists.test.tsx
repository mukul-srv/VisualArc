import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { ProjectList, RecentList, VersionList } from "./lists";
import { shortDate } from "../lib/projects";

const project = { id: "a".repeat(32), name: "House", floor_count: 2, version: 3, updated_at: "2026-05-01T10:20:30+00:00", thumbnail: null };

test("dashboard lists my projects with floors, version and updated", () => {
  const html = renderToStaticMarkup(<ProjectList projects={[project]} />);
  expect(html).toContain(`href="/projects/${project.id}"`);
  expect(html).toContain(">House<");
  expect(html).toContain("<td>2</td>");
  expect(html).toContain("v3");
  expect(html).toContain("2026-05-01 10:20 UTC");
});

test("no projects: empty state links to /new", () => {
  const html = renderToStaticMarkup(<ProjectList projects={[]} />);
  expect(html).toContain("No projects yet");
  expect(html).toContain('href="/new"');
  expect(html).not.toContain("<table");
});

test("recent buildings link to the project floor or the standalone model", () => {
  const g = { generation_id: "b".repeat(32), created_at: "2026-05-01T10:20:30+00:00", project_id: null, project_name: null, floor_id: null, floor_name: null };
  const html = renderToStaticMarkup(
    <RecentList items={[{ ...g, project_id: project.id, project_name: "House", floor_id: "floor-0", floor_name: "Ground" }, g]} />,
  );
  expect(html).toContain(`/viewer?project=${project.id}&amp;floor=floor-0`);
  expect(html).toContain("House / Ground");
  expect(html).toContain(`/viewer?generation=${g.generation_id}`);
  expect(renderToStaticMarkup(<RecentList items={[]} />)).toContain("No buildings generated yet");
});

const versions = [3, 2, 1].map((n) => ({ number: n, created_at: "2026-05-01T10:20:30+00:00", created_by: null, message: `msg ${n}`, floor_count: n - 1 }));

test("version list: newest is current, older ones can be viewed read-only or restored", () => {
  const html = renderToStaticMarkup(<VersionList projectId={project.id} versions={versions} onRestore={() => {}} />);
  expect(html).toContain("Version 3");
  expect(html).toContain("msg 1");
  expect(html).toContain("<em>current</em>");
  expect(html).not.toContain('aria-label="Restore version 3"');
  expect(html).toContain('aria-label="Restore version 2"');
  expect(html).toContain('aria-label="Restore version 1"');
  expect(html).toContain(`/viewer?project=${project.id}&amp;version=2`);
});

test("shortDate is locale independent", () => {
  expect(shortDate("2026-01-02T03:04:05Z")).toBe("2026-01-02 03:04 UTC");
});
