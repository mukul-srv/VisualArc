import { expect, test } from "vitest";
import type { OverlayData } from "./overlay";
import {
  EDIT, EMPTY_HISTORY, addOpeningOp, addWallOp, applyOps, axisOf, canAdd, dragEndpoint, endpointAt, dragged, hitTest, inspectorRows, isNoop, moveWall, nextId,
  openingFromFields, orthogonal, push, redo, removeOpeningOp, removeWallOp, renameRoomOp, setOpeningOp, setWallOp, slideOpening, snap, snapMove, toEditModel,
  undo, wallFromFields, type EditModel, type EditWall,
} from "./plan-edit";

// a 8000 x 5000 plan: a bottom wall with a window, a partition and a room each side
const wall = (id: string, start: [number, number], end: [number, number], handles: string[], thickness = 200): EditWall => ({ id, start, end, thickness, handles, provenance: "source_extracted" });
const m: EditModel = {
  walls: [wall("wall-001", [0, 100], [8000, 100], ["A", "B"]), wall("wall-002", [4000, 200], [4000, 4800], ["C", "D"])],
  openings: [{ id: "opening-001", kind: "window", start: [1000, 100], end: [2200, 100], wall_id: "wall-001", width: 1200, height: 1200, sill: 900, provenance: "source_extracted", handles: ["M1"] }],
  rooms: [
    { id: "room-001", polygon: [[200, 200], [3900, 200], [3900, 4800], [200, 4800]], name: "Room 1", name_source: "defaulted", area: 1, label_point: [2000, 2500] },
    { id: "room-002", polygon: [[4100, 200], [7800, 200], [7800, 4800], [4100, 4800]], name: "Room 2", name_source: "defaulted", area: 1, label_point: [6000, 2500] },
  ],
};

test("hit-test: opening before its wall, wall before room, nothing outside", () => {
  expect(hitTest(m, [1500, 100], 10)).toEqual({ kind: "opening", id: "opening-001" });
  expect(hitTest(m, [3000, 100], 10)).toEqual({ kind: "wall", id: "wall-001" });
  expect(hitTest(m, [4000, 3000], 10)).toEqual({ kind: "wall", id: "wall-002" });
  expect(hitTest(m, [2000, 2500], 10)).toEqual({ kind: "room", id: "room-001" });
  expect(hitTest(m, [-500, -500], 10)).toBeNull();
  expect(endpointAt(m.walls[0], [8005, 100], 20)).toBe("end");
  expect(endpointAt(m.walls[0], [4000, 100], 20)).toBeNull();
});

test("snap: 10 mm grid, then other walls' endpoints within 8 px; the dragged wall is skipped", () => {
  expect(snap([1234, 2678], m, 1)).toEqual([1230, 2680]);
  // scale 0.5 px/mm: 8 px = 16 mm; 4008 is within 16 mm of the partition's x = 4000
  expect(snap([4008, 2678], m, 0.5)).toEqual([4000, 2680]);
  expect(snap([4030, 2678], m, 0.5)).toEqual([4030, 2680]);
  expect(snap([4008, 2678], m, 0.5, "wall-002")).toEqual([4010, 2680]);
  expect(EDIT.snapPx).toBe(8);
});

test("orthogonal forces the dominant axis", () => {
  expect(orthogonal([0, 0], [1000, 120])).toEqual([1000, 0]);
  expect(orthogonal([0, 0], [90, -1000])).toEqual([0, -1000]);
});

test("drag handles: body moves, endpoints change length along the axis, openings slide inside the host", () => {
  expect(moveWall(m.walls[1], [100, -50])).toEqual({ start: [4100, 150], end: [4100, 4750] });
  expect(dragEndpoint(m.walls[1], "end", [4300, 3000])).toEqual({ start: [4000, 200], end: [4000, 3000] }); // x ignored: stays vertical
  expect(dragEndpoint(m.walls[1], "end", [4000, 220])).toBeNull(); // shorter than the minimum
  const host = m.walls[0];
  expect(slideOpening(m.openings[0], host, [500, 300])).toEqual({ start: [1500, 100], end: [2700, 100] });
  expect(slideOpening(m.openings[0], host, [-5000, 0])).toEqual({ start: [0, 100], end: [1200, 100] }); // clamped
  expect(slideOpening(m.openings[0], m.walls[1], [100, 0])).toBeNull(); // not its host's direction
});

test("op builders capture the target snapshot and refuse non-orthogonal geometry", () => {
  const op = setWallOp("e1", m.walls[1], { start: [3000, 200], end: [3000, 4800] })!;
  expect(op).toMatchObject({ op: "set_wall", id: "e1", thickness: 200, target: { start: [4000, 200], end: [4000, 4800], thickness: 200, handles: ["C", "D"] } });
  expect(setWallOp("e1", m.walls[1], { start: [3000, 200], end: [3100, 4800] })).toBeNull();
  expect(addWallOp("e2", [0, 0], [1000, 500])).toBeNull();
  expect(addWallOp("e2", [0, 0], [10, 0])).toBeNull(); // below the minimum length
  expect(addWallOp("e2", [0, 0], [1000, 0])).toMatchObject({ op: "add_wall", thickness: EDIT.defaultThicknessMm });
  expect(removeWallOp("e3", m.walls[0])).toMatchObject({ op: "remove_wall", target: { handles: ["A", "B"] } });
  expect(setOpeningOp("e4", m.openings[0], { height: 1000 })).toEqual({
    op: "set_opening", id: "e4", target: { kind: "window", start: [1000, 100], end: [2200, 100], handles: ["M1"] }, kind: "window", start: [1000, 100], end: [2200, 100], height: 1000,
  });
  expect(removeOpeningOp("e5", m.openings[0]).op).toBe("remove_opening");
  expect(renameRoomOp("e6", m.rooms[0], "  Kitchen ")).toMatchObject({ op: "rename_room", point: [2000, 2500], name: "Kitchen" });
  expect(renameRoomOp("e6", m.rooms[0], "  ")).toBeNull();
});

test("a door goes where clicked, kept inside its wall, and does not fit a short wall", () => {
  const host = m.walls[0];
  expect(addOpeningOp("e1", host, "door", [3000, 100], EDIT.defaultWidthMm.door)).toMatchObject({ op: "add_opening", kind: "door", start: [2550, 100], end: [3450, 100] });
  expect(addOpeningOp("e1", host, "door", [-300, 100], 900)).toMatchObject({ start: [0, 100], end: [900, 100] });
  expect(addOpeningOp("e1", host, "door", [7999, 100], 900)).toMatchObject({ start: [7100, 100], end: [8000, 100] });
  expect(addOpeningOp("e1", { ...host, end: [500, 100] }, "door", [250, 100], 900)).toBeNull();
  expect(addOpeningOp("e1", host, "window", [3000, 100], EDIT.defaultWidthMm.window, { height: 1100 })).toMatchObject({ height: 1100, end: [3600, 100] });
});

test("ids continue after the highest existing one", () => {
  expect(nextId([])).toBe("e1");
  expect(nextId([{ id: "e1" }, { id: "e7" }, { id: "x" }])).toBe("e8");
});

test("undo and redo walk the pending list; a new op drops the redo tail; the server limit is respected", () => {
  const [a, b, c] = ["e1", "e2", "e3"].map((id) => removeWallOp(id, m.walls[0]));
  let h = push(push(EMPTY_HISTORY, a), b);
  expect(h.done.map((o) => o.id)).toEqual(["e1", "e2"]);
  h = undo(h);
  expect([h.done.map((o) => o.id), h.undone.map((o) => o.id)]).toEqual([["e1"], ["e2"]]);
  expect(redo(h).done.map((o) => o.id)).toEqual(["e1", "e2"]);
  h = push(h, c);
  expect(h.undone).toEqual([]);
  expect(undo(EMPTY_HISTORY)).toBe(EMPTY_HISTORY);
  expect(redo(EMPTY_HISTORY)).toBe(EMPTY_HISTORY);
  expect(canAdd(EDIT.maxEdits - 2, h)).toBe(false);
  expect(canAdd(0, h)).toBe(true);
});

test("preview: a moved wall carries its opening, a removed wall takes it, added things appear, rooms are renamed", () => {
  const moved = applyOps(m, [setWallOp("e1", m.walls[0], { start: [0, 600], end: [8000, 600] })!]);
  expect(moved.walls[0]).toMatchObject({ id: "wall-001", start: [0, 600], handles: ["e1"] });
  expect(moved.openings[0]).toMatchObject({ start: [1000, 600], end: [2200, 600] });
  expect(applyOps(m, [removeWallOp("e1", m.walls[0])]).openings).toEqual([]);
  const added = applyOps(m, [addWallOp("e1", [6000, 200], [6000, 4800])!, addOpeningOp("e2", m.walls[0], "door", [5000, 100], 900)!, removeOpeningOp("e3", m.openings[0])]);
  expect(added.walls.map((w) => w.id)).toEqual(["wall-001", "wall-002", "new-e1"]);
  expect(added.openings.map((o) => [o.id, o.kind, o.wall_id])).toEqual([["new-e2", "door", "wall-001"]]);
  expect(applyOps(m, [renameRoomOp("e1", m.rooms[1], "Hall")!]).rooms[1]).toMatchObject({ name: "Hall", name_source: "user_modified" });
  // a second op targets the first one's result (its handle is the op id), as on the server
  const twice = applyOps(m, [setWallOp("e1", m.walls[1], { start: [3000, 200], end: [3000, 4800] })!]);
  const again = applyOps(twice, [setWallOp("e2", twice.walls[1], { start: [3200, 200], end: [3200, 4800] })!]);
  expect(again.walls[1]).toMatchObject({ start: [3200, 200], handles: ["e2"] });
  // a stale target changes nothing
  expect(applyOps(m, [removeWallOp("e9", { ...m.walls[0], handles: ["Z"] })])).toEqual(m);
});

test("inspector rows put the source next to the edited value", () => {
  const now = applyOps(m, [setWallOp("e1", m.walls[1], { start: [3000, 200], end: [3000, 4800] }, 300)!]);
  const rows = inspectorRows(m, now, { kind: "wall", id: "wall-002" });
  expect(rows.find((r) => r.label === "Start (mm)")).toEqual({ label: "Start (mm)", source: "4000, 200", edited: "3000, 200", changed: true });
  expect(rows.find((r) => r.label === "Thickness (mm)")).toMatchObject({ source: "200", edited: "300", changed: true });
  expect(rows.find((r) => r.label === "End (mm)")).toMatchObject({ changed: true });
  const op = inspectorRows(m, m, { kind: "opening", id: "opening-001" });
  expect(op.find((r) => r.label === "Offset on wall (mm)")).toMatchObject({ source: "1000", edited: "1000", changed: false });
  const added = applyOps(m, [addWallOp("e1", [6000, 200], [6000, 4800])!]);
  expect(inspectorRows(m, added, { kind: "wall", id: "new-e1" })[0]).toMatchObject({ source: "(new)", changed: true });
  expect(inspectorRows(m, m, { kind: "room", id: "room-001" })).toEqual([{ label: "Name", source: "Room 1", edited: "Room 1", changed: false }]);
});

test("inspector fields: orthogonal walls only, openings must lie in their wall", () => {
  expect(wallFromFields({ sx: "0", sy: "0", ex: "1000", ey: "0", thickness: "200" })).toEqual({ ok: true, value: { start: [0, 0], end: [1000, 0], thickness: 200 } });
  expect(wallFromFields({ sx: "0", sy: "0", ex: "1000", ey: "100", thickness: "200" })).toMatchObject({ ok: false });
  expect(wallFromFields({ sx: "0", sy: "0", ex: "x", ey: "0", thickness: "200" })).toMatchObject({ ok: false });
  expect(wallFromFields({ sx: "0", sy: "0", ex: "1000", ey: "0", thickness: "0" })).toMatchObject({ ok: false });
  const host = m.walls[0];
  expect(openingFromFields(host, { offset: "500", width: "900", height: "", sill: "" })).toEqual({ ok: true, value: { start: [500, 100], end: [1400, 100] } });
  expect(openingFromFields(host, { offset: "500", width: "900", height: "2000", sill: "0" })).toMatchObject({ ok: true, value: { height: 2000, sill_height: 0 } });
  expect(openingFromFields(host, { offset: "7500", width: "900", height: "", sill: "" })).toMatchObject({ ok: false });
  expect(openingFromFields(host, { offset: "0", width: "900", height: "-1", sill: "" })).toMatchObject({ ok: false });
});

test("toEditModel reads the overlay and refuses data from before editing support", () => {
  const d: OverlayData = {
    floor_id: "f", unit: "mm", source: { segments: [], total: 0, truncated: false },
    model: {
      walls: [{ id: "wall-001", start: [0, 100], end: [8000, 100], thickness: 200, handles: ["A"], provenance: "source_extracted" }],
      junctions: [], boundaries: [],
      openings: [{ id: "opening-001", kind: "door", start: [1000, 100], end: [1900, 100], inferred: false, wall_id: "wall-001", width: 900, height: 2100, sill: 0, provenance: "source_extracted", handles: ["M"] }],
      rooms: [{ id: "room-001", polygon: [[0, 0], [1, 0], [1, 1]], name: "R", name_source: "defaulted", area: 1, label_point: [0.5, 0.2] }],
    },
  };
  expect(toEditModel(d)?.openings[0]).toMatchObject({ kind: "door", wall_id: "wall-001", height: 2100 });
  expect(toEditModel({ ...d, model: { ...d.model, rooms: undefined } })).toBeNull();
  expect(toEditModel({ ...d, model: { ...d.model, walls: [{ ...d.model.walls[0], handles: undefined }] } })).toBeNull();
  expect(axisOf([0, 0], [10, 0])).toBe("h");
  expect(axisOf([0, 0], [0, 0])).toBeNull();
});

test("a click that moves nothing is not an edit: not a drag, and no-op ops are recognised", () => {
  expect(dragged([100, 100], [100, 100], 0.5)).toBe(false);
  expect(dragged([100, 100], [102, 100], 0.5)).toBe(false); // 1 px
  expect(dragged([100, 100], [110, 100], 0.5)).toBe(true); // 5 px
  const w = m.walls[1];
  expect(isNoop(setWallOp("e1", w, { start: w.start, end: w.end })!)).toBe(true);
  expect(isNoop(setWallOp("e1", w, { start: [4000, 200], end: [4000, 4800] }, 300)!)).toBe(false);
  expect(isNoop(setWallOp("e1", w, { start: [4010, 200], end: [4010, 4800] })!)).toBe(false);
  const o = m.openings[0];
  expect(isNoop(setOpeningOp("e2", o))).toBe(true);
  expect(isNoop(setOpeningOp("e2", o, { height: 1000 }))).toBe(false);
  expect(isNoop(setOpeningOp("e2", o, { kind: "door" }))).toBe(false);
  expect(isNoop(removeWallOp("e3", w))).toBe(false);
});

test("a wall move snaps by whichever end snaps nearest", () => {
  const w = m.walls[1]; // x = 4000, y 200..4800
  // moving by (-1010, 0) puts the wall at x = 2990; at 0.5 px/mm the grid is closer than any wall: delta lands on the grid
  expect(snapMove(w, [-1003, 0], m, 0.5)).toEqual([-1000, 0]);
  // the end that needs the smaller adjustment decides: start 3 mm from wall-001's y = 100, end 4 mm off the grid
  const near = { ...w, start: [4000, 103] as [number, number], end: [4000, 4704] as [number, number] };
  expect(snapMove(near, [0, 0], m, 0.5)).toEqual([0, -3]);
  const far = { ...w, start: [4000, 112] as [number, number], end: [4000, 4704] as [number, number] };
  expect(snapMove(far, [0, 0], m, 0.5)).toEqual([0, -4]);
});
