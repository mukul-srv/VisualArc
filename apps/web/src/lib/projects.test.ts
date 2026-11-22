import { expect, test, vi } from "vitest";
import { removeFloor, renameFloor, saveAsProject } from "./projects";

const f = (status = 200, body: unknown = {}) => vi.fn(async () => new Response(status === 204 ? null : JSON.stringify(body), { status })) as unknown as typeof fetch;
const lastCall = (m: typeof fetch) => (m as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];

test("rename and remove a floor call the floor endpoints", async () => {
  const a = f();
  expect(await renameFloor("p1", "floor-0", "Basement", a)).toMatchObject({ ok: true });
  const [u, init] = lastCall(a);
  expect([u, init.method, init.body]).toEqual(["/api/v1/projects/p1/floors/floor-0", "PATCH", JSON.stringify({ name: "Basement" })]);
  const b = f(204);
  expect(await removeFloor("p1", "floor-0", b)).toMatchObject({ ok: true });
  expect([lastCall(b)[0], lastCall(b)[1].method]).toEqual(["/api/v1/projects/p1/floors/floor-0", "DELETE"]);
});

test("save as project returns the new id; a 4xx message is surfaced", async () => {
  expect(await saveAsProject("g1", "Saved", f(201, { project_id: "p9" }))).toMatchObject({ ok: true, project_id: "p9" });
  expect(await saveAsProject("g1", "Saved", f(409, { detail: "this model already belongs to a project" }))).toMatchObject({ ok: false, message: "this model already belongs to a project" });
});
