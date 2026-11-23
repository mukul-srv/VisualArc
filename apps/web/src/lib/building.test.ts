import { expect, test, vi } from "vitest";
import { confirmPairing, pairRows, setOffset, unpair, unpairedStairs, type Building } from "./building";

const b = {
  floors: [
    { id: "floor-1", name: "First", stairs: [{ id: "t1" }] },
    { id: "floor-0", name: "Ground", stairs: [{ id: "s1" }, { id: "s2" }] },
  ],
  pairings: [{ lower_floor: "floor-0", lower_stair: "s1", upper_floor: "floor-1", upper_stair: "t1", status: "auto", overlap: 0.904 }],
} as unknown as Building;

test("pairRows names floors and rounds overlap", () => {
  const [r] = pairRows(b);
  expect(r).toMatchObject({ label: "Ground s1 to First t1", status: "auto", overlapPct: 90 });
});

test("unpairedStairs lists stairs without an upward pair (rejected counts as unpaired)", () => {
  expect(unpairedStairs(b, "floor-0")).toEqual(["s2"]);
  const rejected = { ...b, pairings: b.pairings.map((p) => ({ ...p, status: "rejected" })) } as Building;
  expect(unpairedStairs(rejected, "floor-0")).toEqual(["s1", "s2"]);
});

const ok = () => vi.fn(async () => new Response("{}")) as unknown as typeof fetch;
const call = (m: typeof fetch) => (m as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];

test("offset, confirm and unpair hit their endpoints", async () => {
  const a = ok();
  await setOffset("p", "floor-1", 5, -2, a);
  expect([call(a)[0], call(a)[1].method, call(a)[1].body]).toEqual(["/api/v1/projects/p/floors/floor-1/offset", "PUT", '{"x":5,"y":-2}']);
  const ref = pairRows(b)[0].ref;
  const c = ok();
  await confirmPairing("p", ref, c);
  expect([call(c)[0], call(c)[1].method]).toEqual(["/api/v1/projects/p/building/pairings", "PUT"]);
  const d = ok();
  await unpair("p", ref, d);
  expect([call(d)[0], call(d)[1].method]).toEqual(["/api/v1/projects/p/building/pairings/unpair", "POST"]);
});
