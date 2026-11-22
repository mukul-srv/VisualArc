import { expect, test, vi } from "vitest";
import { DEFAULT_CONVENTIONS, inspectLayers, isDefault, putProjectConventions } from "./conventions";

const ok = (body: unknown) => vi.fn(async () => new Response(JSON.stringify(body))) as unknown as typeof fetch;

test("only a non-default selection is sent with a request", () => {
  expect(isDefault(DEFAULT_CONVENTIONS)).toBe(true);
  expect(isDefault({ preset: "iso13567", mapping: {} })).toBe(false);
  expect(isDefault({ preset: "aia", mapping: { WALLS: "wall" } })).toBe(false);
});

test("inspectLayers posts the spec and returns layers with the re-run preflight", async () => {
  const f = ok({ layers: [{ layer: "WALLS", role: null, entities: 3 }], issues: [], needs: [], floor_candidates: [] });
  const r = await inspectLayers("u1", { preset: "custom", mapping: { WALLS: "wall" } }, f);
  expect(r).toMatchObject({ ok: true, layers: [{ layer: "WALLS", role: null }] });
  const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/v1/uploads/u1/layers");
  expect(JSON.parse(init.body as string)).toEqual({ preset: "custom", mapping: { WALLS: "wall" } });
});

test("a rejected mapping surfaces the server message", async () => {
  const f = vi.fn(async () => new Response(JSON.stringify({ detail: "layer 'A-WALL' is already mapped" }), { status: 422 })) as unknown as typeof fetch;
  expect(await putProjectConventions("p", { preset: "aia", mapping: { "A-WALL": "door" } }, f)).toMatchObject({ ok: false, kind: "rejected" });
});
