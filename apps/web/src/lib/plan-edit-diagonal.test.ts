import { expect, test } from "vitest";
import {
  angleDeg, applyOps, atF, constrain, dragEndpoint, dragOpeningOp, frameOf, hitTest, inspectorRows, openingFromFields, polar, setWallOp, slideOpening, snap, toS, toV,
  wallFromPolar, type EditModel, type Pt,
} from "./plan-edit";

// a 45 degree wall of length 2000*sqrt(2) from (0, 0) to (2000, 2000), 200 thick, with a 900 wide door 600 from its start
const L = 2000 * Math.SQRT2;
const wall = { id: "wall-001", start: [0, 0] as Pt, end: [2000, 2000] as Pt, thickness: 200, handles: ["W"], provenance: "source_extracted" };
const f = frameOf(wall.start, wall.end);
const door = { id: "opening-001", kind: "door" as const, start: atF(f, 600), end: atF(f, 1500), wall_id: wall.id, width: 900, height: 2100, sill: 0, provenance: "source_extracted", handles: ["D"] };
const model: EditModel = { walls: [wall], openings: [door], rooms: [] };
const ends = (op: unknown) => op as { start: Pt; end: Pt };

test("frame: along and across a wall, and back", () => {
  expect(f.len).toBeCloseTo(L);
  expect(toS(f, [1000, 1000])).toBeCloseTo(L / 2);
  expect(toV(f, [1000, 1000])).toBeCloseTo(0);
  expect(toV(f, [-100, 100])).toBeCloseTo(100 * Math.SQRT2); // left of the direction is +v
  const p = atF(f, 700, 50);
  expect(toS(f, p)).toBeCloseTo(700);
  expect(toV(f, p)).toBeCloseTo(50);
});

test("angle and polar are inverse, counter-clockwise from +x with y up", () => {
  expect(angleDeg([0, 0], [1000, 1000])).toBeCloseTo(45);
  expect(angleDeg([0, 0], [-1000, 0])).toBeCloseTo(180);
  expect(angleDeg([0, 0], [0, -1000])).toBeCloseTo(270);
  const e = polar([100, 100], 1000, 30);
  expect(e[0]).toBeCloseTo(100 + 1000 * Math.cos(Math.PI / 6));
  expect(e[1]).toBeCloseTo(600);
  expect(wallFromPolar({ sx: "0", sy: "0", length: "1000", angle: "90", thickness: "200" })).toEqual({ ok: true, value: { start: [0, 0], end: [0, 1000], thickness: 200 } });
  expect(wallFromPolar({ sx: "0", sy: "0", length: "10", angle: "0", thickness: "200" })).toMatchObject({ ok: false });
});

test("angle snap: 45 and 15 degree steps put the dominant coordinate on the grid; ortho and free are as before", () => {
  expect(constrain([0, 0], [2003, 1990], "snap45")).toEqual([2000, 2000]);
  expect(constrain([0, 0], [2000, 60], "snap45")).toEqual([2000, 0]);
  const e = constrain([0, 0], [1000, 560], "snap15"); // 29.2 degrees -> 30
  expect(angleDeg([0, 0], e)).toBeCloseTo(30, 4);
  expect(e[0]).toBe(1000);
  expect(constrain([100, 100], [100, 900], "snap15")).toEqual([100, 900]);
  expect(constrain([0, 0], [1000, 120], "ortho")).toEqual([1000, 0]);
  expect(constrain([0, 0], [1000, 120], "free")).toEqual([1000, 120]);
});

test("hit-test finds a diagonal wall and its opening inside the footprint only", () => {
  expect(hitTest(model, [300, 320], 5)).toEqual({ kind: "wall", id: "wall-001" }); // 14 mm off the line, inside the 100 mm half thickness
  expect(hitTest(model, [300, 600], 5)).toBeNull(); // 212 mm off the wall
  expect(hitTest(model, atF(f, 1000), 5)).toEqual({ kind: "opening", id: "opening-001" });
  expect(hitTest(model, atF(f, 200), 5)).toEqual({ kind: "wall", id: "wall-001" }); // beside the door
});

test("endpoint drag: ortho mode keeps the direction (length only), angle modes turn the wall", () => {
  const g = dragEndpoint(wall, "end", [3000, 3500], "ortho")!;
  expect(angleDeg(g.start, g.end)).toBeCloseTo(45);
  expect(g.end[0]).toBeCloseTo(3250);
  expect(dragEndpoint(wall, "end", [2000, 60], "snap45")!.end).toEqual([2000, 0]);
  expect(dragEndpoint(wall, "end", [10, 10], "free")).toBeNull(); // shorter than the minimum
});

test("an opening slides along a diagonal host and stops at its ends", () => {
  const s = slideOpening(door, wall, [300, 300])!; // 300*sqrt2 along
  expect(toS(f, s.start)).toBeCloseTo(600 + 300 * Math.SQRT2);
  expect(toS(f, slideOpening(door, wall, [5000, 5000])!.end)).toBeCloseTo(L);
  expect(toS(f, slideOpening(door, wall, [-5000, -5000])!.start)).toBeCloseTo(0);
  expect(slideOpening(door, { ...wall, end: [2000, 0] }, [10, 0])).toBeNull(); // not parallel to its host
});

test("drag-adding a door onto a diagonal wall: offset along the wall, on the grid, clamped to the free gap", () => {
  const op = dragOpeningOp("e1", wall, "door", atF(f, 1700), atF(f, 2300), [door], {})!;
  expect(op).toMatchObject({ op: "add_opening", kind: "door" });
  const [a, b] = [toS(f, ends(op).start), toS(f, ends(op).end)].sort((x, y) => x - y);
  expect(a).toBeCloseTo(1700, -1);
  expect(b - a).toBeCloseTo(600, -1);
  expect(dragOpeningOp("e1", wall, "door", atF(f, 1000), atF(f, 1200), [door], {})).toBeNull(); // pressed on the door
  const clamped = dragOpeningOp("e1", wall, "window", atF(f, 1600), atF(f, 5000), [door], {})!;
  expect(toS(f, ends(clamped).end)).toBeCloseTo(L, 0);
  expect(ends(op).start[1]).toBeLessThanOrEqual(ends(op).end[1]); // lower y first, as the server wants
});

test("snapping reaches a point on an angled wall's centreline", () => {
  const m: EditModel = { walls: [wall], openings: [], rooms: [] };
  const q = snap([1003, 996], m, 1); // 1 px per mm, snap radius 8 px: about 5 mm from the line
  expect(toV(f, q)).toBeCloseTo(0, 6);
  expect(snap([1500, 1000], m, 1)).toEqual([1500, 1000]); // far from the line: the grid
});

test("moving a diagonal wall takes its opening along (same length) and drops it when it no longer fits", () => {
  const moved = applyOps(model, [setWallOp("e1", wall, { start: [500, 0], end: [2500, 2000] })!]);
  expect(moved.openings[0].start[0]).toBeCloseTo(door.start[0] + 500);
  expect(applyOps(model, [setWallOp("e1", wall, { start: [0, 0], end: [400, 400] })!]).openings).toHaveLength(0); // ends before the door
  const longer = applyOps(model, [setWallOp("e1", wall, { start: [0, 0], end: [3000, 3000] })!]); // the door stays where it is
  expect(longer.openings[0].start[0]).toBeCloseTo(door.start[0]);
});

test("inspector: length, angle and the opening offset along a diagonal wall; fields place an opening by offset and width", () => {
  const rows = inspectorRows(model, model, { kind: "wall", id: "wall-001" });
  expect(rows.find((r) => r.label === "Angle")?.edited).toBe("45°");
  expect(rows.find((r) => r.label === "Length (mm)")?.edited).toBe(`${Math.round(L * 10) / 10}`);
  expect(inspectorRows(model, model, { kind: "opening", id: "opening-001" }).find((r) => r.label === "Offset on wall (mm)")?.edited).toBe("600");
  const r = openingFromFields(wall, { offset: "600", width: "900", height: "", sill: "" });
  expect(r.ok && toS(f, r.value.start)).toBeCloseTo(600);
  expect(openingFromFields(wall, { offset: "2500", width: "900", height: "", sill: "" })).toMatchObject({ ok: false });
});
