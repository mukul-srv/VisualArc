import { expect, test } from "vitest";
import { fit, getPlanOverlay, overlayBounds, toScreen, wallCorners, type OverlayData } from "./overlay";

const d: OverlayData = {
  floor_id: "f",
  unit: "mm",
  source: { segments: [{ layer: "A-WALL", wall: true, p: [0, 0, 4000, 0] }, { layer: "X", wall: false, p: [-500, 0, -500, 2000] }], total: 2, truncated: false },
  model: {
    walls: [{ id: "w", start: [0, 100], end: [4000, 100], thickness: 200 }],
    junctions: [],
    openings: [{ id: "o", kind: "door", start: [1000, 100], end: [1900, 100], inferred: true }],
    boundaries: [{ polygon: [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], inferred: false }],
  },
};

test("bounds cover the source and the model; empty gives null", () => {
  expect(overlayBounds(d)).toEqual({ minX: -500, minY: 0, maxX: 4000, maxY: 3000 });
  expect(overlayBounds({ ...d, source: { ...d.source, segments: [] }, model: { walls: [], junctions: [], openings: [], boundaries: [] } })).toBeNull();
});

test("fit keeps the aspect ratio and the drawing inside the canvas; plan up is screen up", () => {
  const b = overlayBounds(d)!;
  const f = fit(b, 500, 400, 10);
  const [x0, y0] = toScreen(f, b.minX, b.minY);
  const [x1, y1] = toScreen(f, b.maxX, b.maxY);
  for (const v of [x0, x1]) {
    expect(v).toBeGreaterThanOrEqual(10 - 1e-9);
    expect(v).toBeLessThanOrEqual(490 + 1e-9);
  }
  for (const v of [y0, y1]) {
    expect(v).toBeGreaterThanOrEqual(10 - 1e-9);
    expect(v).toBeLessThanOrEqual(390 + 1e-9);
  }
  expect(y1).toBeLessThan(y0); // the top of the plan is higher on screen
  expect((x1 - x0) / (y0 - y1)).toBeCloseTo((b.maxX - b.minX) / (b.maxY - b.minY));
});

test("fit survives a degenerate drawing (a single point)", () => {
  const f = fit({ minX: 5, minY: 5, maxX: 5, maxY: 5 }, 300, 200);
  expect(Number.isFinite(f.scale) && f.scale > 0).toBe(true);
});

test("wall corners follow the direction of the wall", () => {
  expect(wallCorners({ start: [0, 100], end: [4000, 100], thickness: 200 })).toEqual([[0, 0], [4000, 0], [4000, 200], [0, 200]]);
  expect(wallCorners({ start: [50, 0], end: [50, 900], thickness: 100 })).toEqual([[0, 0], [0, 900], [100, 900], [100, 0]]);
});

test("getPlanOverlay reads the floor plan endpoint and passes the share token", async () => {
  let url = "";
  const f = (async (u: string) => {
    url = u;
    return new Response(JSON.stringify(d));
  }) as unknown as typeof fetch;
  const r = await getPlanOverlay("p1", "floor-0", f, "tok");
  expect(r.ok && r.overlay.floor_id).toBe("f");
  expect(url).toBe("/api/v1/projects/p1/floors/floor-0/plan?share=tok");
});
