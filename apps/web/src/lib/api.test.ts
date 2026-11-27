import { expect, test } from "vitest";
import { generate, importIfc, uploadDxf } from "./api";

const reply = (status: number, body: unknown) =>
  (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

test("upload posts the raw file body and returns preflight", async () => {
  let seen: { url: string; init: RequestInit } | undefined;
  const f = (async (url: string, init: RequestInit) => {
    seen = { url, init };
    return new Response(
      JSON.stringify({ upload_id: "a".repeat(32), issues: [], needs: ["units"], inventory: { layers: [], entity_counts: {} } }),
      { status: 201 },
    );
  }) as unknown as typeof fetch;
  const file = new Blob(["dxf"]);
  const r = await uploadDxf(file, f);
  expect(r.ok && r.needs).toEqual(["units"]);
  expect(seen!.url).toMatch(/\/api\/v1\/uploads$/);
  expect(seen!.init.body).toBe(file);
});

test("422 is a rejection that names the file, lists accepted types and says what to do next", async () => {
  const file = Object.assign(new Blob(), { name: "plan.txt" });
  const r = await uploadDxf(file, reply(422, { detail: "not a DXF file: bad header in the uploaded file." }));
  expect(r).toMatchObject({ ok: false, kind: "rejected" });
  const m = !r.ok ? r.message : "";
  expect(m).toContain('"plan.txt"');
  expect(m).toContain("not a DXF file");
  expect(m).toContain("DXF, DWG, IFC or PDF");
  expect(m).toContain("Choose a floor plan file.");
});

test("413 is a rejection", async () => {
  expect(await uploadDxf(new Blob(), reply(413, { detail: "too big" }))).toMatchObject({ kind: "rejected" });
});

test("409 carries structured blocking issues", async () => {
  const issues = [{ code: "wall_height_missing", severity: "blocking", message: "m", sources: [] }];
  const r = await generate({ upload_id: "x" }, reply(409, { detail: "blocked", issues }));
  expect(r).toMatchObject({ ok: false, kind: "blocked", issues });
});

test("network failure is an actionable error, not a throw", async () => {
  const f = (async () => {
    throw new TypeError("fail");
  }) as unknown as typeof fetch;
  const r = await generate({ upload_id: "x" }, f);
  expect(r).toMatchObject({ ok: false, kind: "error" });
  expect(!r.ok && r.message).toMatch(/backend running/);
});

test("importIfc posts the project name to the upload's ifc endpoint", async () => {
  let seen: { url: string; body: string } | undefined;
  const f = (async (url: string, init: RequestInit) => {
    seen = { url, body: String(init.body) };
    return new Response(JSON.stringify({ project_id: "p".repeat(32), issues: [] }), { status: 201 });
  }) as unknown as typeof fetch;
  const r = await importIfc("u".repeat(32), "House", f);
  expect(r.ok && r.project_id).toBe("p".repeat(32));
  expect(seen!.url).toMatch(/\/uploads\/u{32}\/ifc$/);
  expect(JSON.parse(seen!.body)).toEqual({ project_name: "House" });
});
