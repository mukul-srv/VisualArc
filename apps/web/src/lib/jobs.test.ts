import { expect, test, vi } from "vitest";
import { addFloorJob, generateJob } from "./jobs";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const seq = (...rs: Response[]) => vi.fn(async () => rs.shift()!) as unknown as typeof fetch;

test("polls through stages and resolves with the result", async () => {
  const seen: string[] = [];
  const f = seq(
    json({ job_id: "j" }, 202),
    json({ status: "running", stage: "parsing", progress: 10, error: null, result: null }),
    json({ status: "running", stage: "exporting", progress: 75, error: null, result: null }),
    json({ status: "succeeded", stage: "done", progress: 100, error: null, result: { generation_id: "g", issues: [] } }),
  );
  const r = await generateJob({ upload_id: "u" }, (p) => seen.push(p.stage), f, 0);
  expect(seen).toEqual(["parsing", "exporting", "done"]);
  expect(r).toMatchObject({ ok: true, generation_id: "g" });
});

test("a failed job reports its error; blocking issues map to blocked", async () => {
  const bad = seq(json({ job_id: "j" }, 202), json({ status: "failed", stage: "parsing", progress: 10, error: "boom", result: null }));
  expect(await addFloorJob("p", { upload_id: "u", floor_name: "G" }, undefined, bad, 0)).toMatchObject({ ok: false, kind: "error", message: "boom" });
  const blocked = seq(json({ job_id: "j" }, 202), json({ status: "failed", stage: "building-model", progress: 50, error: "Blocking issues", result: { issues: [{ code: "X" }] } }));
  expect(await generateJob({ upload_id: "u" }, undefined, blocked, 0)).toMatchObject({ ok: false, kind: "blocked", issues: [{ code: "X" }] });
});

test("start failure (viewer 404) is returned as is", async () => {
  const r = await generateJob({ upload_id: "u" }, undefined, seq(json({ detail: "unknown upload_id" }, 404)), 0);
  expect(r).toMatchObject({ ok: false, message: "unknown upload_id" });
});

test("transient poll errors are retried, then the job result is used", async () => {
  const f = seq(
    json({ job_id: "j" }, 202),
    json({ detail: "oops" }, 502),
    json({ detail: "oops" }, 502),
    json({ status: "succeeded", stage: "done", progress: 100, error: null, result: { generation_id: "g", issues: [] } }),
  );
  expect(await generateJob({ upload_id: "u" }, undefined, f, 0)).toMatchObject({ ok: true, generation_id: "g" });
});

test("persistent poll errors fail; 404 fails at once", async () => {
  const many = vi.fn(async (u: RequestInfo | URL) => (String(u).endsWith("/generations") ? json({ job_id: "j" }, 202) : json({}, 502))) as unknown as typeof fetch;
  expect(await generateJob({ upload_id: "u" }, undefined, many, 0)).toMatchObject({ ok: false, kind: "error" });
  const gone = seq(json({ job_id: "j" }, 202), json({ detail: "unknown job" }, 404));
  expect(await generateJob({ upload_id: "u" }, undefined, gone, 0)).toMatchObject({ ok: false, message: "unknown job" });
});
