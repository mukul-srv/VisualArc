import type { OverlayData } from "./overlay";

// Pure logic of the plan editor: hit-testing, snapping, drag handles, op builders, undo/redo and a local
// preview. The preview only moves the edited rectangles; rooms, junctions and every geometry rule stay on
// the server, which re-derives the floor on save and is the source of truth.
export type Pt = [number, number];

/** Every editor constant in one place. */
export const EDIT = {
  gridMm: 10,
  snapPx: 8, // snap to other walls' endpoints/axes within this many screen pixels
  hitPx: 6, // click tolerance in screen pixels
  minWallMm: 50, // UI guard only; the server's limits live in services/api/src/api/engine/settings.py
  defaultThicknessMm: 200,
  minOpeningMm: 300, // UI guard for a dragged opening; the server validates the rest
  maxEdits: 500, // mirrors Settings.max_edits (services/api/src/api/engine/settings.py)
  tolMm: 1, // mirrors Settings.edit_match_tolerance_mm (same file)
  dragMinPx: 3, // a click that moves less than this is a click, not a drag
} as const;

// --- ops: mirror services/api/src/api/engine/edits.py ----------------------------------------------------------
export type Kind = "door" | "window";
export type WallRef = { start: Pt; end: Pt; thickness: number; handles: string[] };
export type OpeningRef = { kind: Kind; start: Pt; end: Pt; handles: string[] };
type Dims = { height?: number; sill_height?: number };
export type EditOp =
  | { op: "set_wall"; id: string; target: WallRef; start: Pt; end: Pt; thickness: number }
  | { op: "add_wall"; id: string; start: Pt; end: Pt; thickness: number }
  | { op: "remove_wall"; id: string; target: WallRef }
  | ({ op: "set_opening"; id: string; target: OpeningRef; kind: Kind; start: Pt; end: Pt } & Dims)
  | ({ op: "add_opening"; id: string; wall: WallRef; kind: Kind; start: Pt; end: Pt } & Dims)
  | { op: "remove_opening"; id: string; target: OpeningRef }
  | { op: "rename_room"; id: string; point: Pt; name: string };

// --- the model the editor works on (from the plan overlay) -------------------------------------------------------
export type EditWall = { id: string; start: Pt; end: Pt; thickness: number; handles: string[]; provenance: string };
export type EditOpening = { id: string; kind: Kind; start: Pt; end: Pt; wall_id: string; width: number; height: number | null; sill: number | null; provenance: string; handles: string[] };
export type EditRoom = { id: string; polygon: Pt[]; name: string; name_source: string; area: number; label_point: Pt };
export type EditModel = { walls: EditWall[]; openings: EditOpening[]; rooms: EditRoom[] };
export type Selection = { kind: "wall" | "opening" | "room"; id: string };

/** The overlay's model for editing; null when the data predates editing support (no handles). */
export function toEditModel(d: OverlayData): EditModel | null {
  const m = d.model;
  if (!m.rooms || m.walls.some((w) => !w.handles) || m.openings.some((o) => !o.handles || o.wall_id === undefined)) return null;
  return {
    walls: m.walls.map((w) => ({ id: w.id, start: w.start, end: w.end, thickness: w.thickness, handles: w.handles!, provenance: w.provenance ?? "" })),
    openings: m.openings.map((o) => ({
      id: o.id, kind: o.kind as Kind, start: o.start, end: o.end, wall_id: o.wall_id!, width: o.width ?? Math.abs(o.end[0] - o.start[0]) + Math.abs(o.end[1] - o.start[1]),
      height: o.height ?? null, sill: o.sill ?? null, provenance: o.provenance ?? "", handles: o.handles!,
    })),
    rooms: m.rooms.map((r) => ({ ...r })),
  };
}

// --- small geometry ------------------------------------------------------------------------------------------------
type Axis = "h" | "v";
export function axisOf(a: Pt, b: Pt): Axis | null {
  const dx = Math.abs(b[0] - a[0]), dy = Math.abs(b[1] - a[1]);
  if (dy <= EDIT.tolMm && dx > EDIT.tolMm) return "h";
  if (dx <= EDIT.tolMm && dy > EDIT.tolMm) return "v";
  return null;
}
const along = (a: Axis, p: Pt) => (a === "h" ? p[0] : p[1]);
const cross = (a: Axis, p: Pt) => (a === "h" ? p[1] : p[0]);
const at = (a: Axis, t: number, c: number): Pt => (a === "h" ? [t, c] : [c, t]);
const span = (a: Axis, s: Pt, e: Pt): [number, number] => [Math.min(along(a, s), along(a, e)), Math.max(along(a, s), along(a, e))];
const near = (a: Pt, b: Pt) => Math.abs(a[0] - b[0]) <= EDIT.tolMm && Math.abs(a[1] - b[1]) <= EDIT.tolMm;
const lengthOf = (s: Pt, e: Pt) => Math.hypot(e[0] - s[0], e[1] - s[1]);

// --- walls off the axes: a wall's own frame (s along start -> end, v across it), as in edits.py ---------------------
export type Frame = { o: Pt; u: Pt; n: Pt; len: number };
export function frameOf(a: Pt, b: Pt): Frame {
  const len = lengthOf(a, b);
  const u: Pt = [(b[0] - a[0]) / len, (b[1] - a[1]) / len];
  return { o: a, u, n: [-u[1], u[0]], len };
}
export const toS = (f: Frame, p: Pt) => (p[0] - f.o[0]) * f.u[0] + (p[1] - f.o[1]) * f.u[1];
export const toV = (f: Frame, p: Pt) => (p[0] - f.o[0]) * f.n[0] + (p[1] - f.o[1]) * f.n[1];
export const atF = (f: Frame, s: number, v = 0): Pt => [f.o[0] + s * f.u[0] + v * f.n[0], f.o[1] + s * f.u[1] + v * f.n[1]];
/** A diagonal span starts at its lower y (then x), like the server's. */
const lowYFirst = (a: Pt, b: Pt): [Pt, Pt] => (a[1] < b[1] || (a[1] === b[1] && a[0] <= b[0]) ? [a, b] : [b, a]);
/** The direction of a wall in degrees, 0..360, counter-clockwise from +x (plan y is up). */
export const angleDeg = (a: Pt, b: Pt) => ((Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI + 360) % 360;
/** The end of a wall from its start, a length and a direction in degrees. */
export const polar = (a: Pt, length: number, deg: number): Pt => [a[0] + length * Math.cos((deg * Math.PI) / 180), a[1] + length * Math.sin((deg * Math.PI) / 180)];
const parallel = (a: Pt, b: Pt, c: Pt, d: Pt) => Math.abs((b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])) <= 1e-3 * lengthOf(a, b) * lengthOf(c, d);

export function pointInPolygon(p: Pt, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Plan-mm tolerance of a pixel count at this scale (px per mm). */
export const pxToMm = (px: number, scale: number) => px / scale;

// --- hit-test ------------------------------------------------------------------------------------------------------
const hostOf = (m: EditModel, o: EditOpening) => m.walls.find((w) => w.id === o.wall_id);

/** What is under `p` (plan mm): an opening first, then a wall, then a room. `tol` in mm. */
export function hitTest(m: EditModel, p: Pt, tol: number): Selection | null {
  for (const o of m.openings) {
    const a = axisOf(o.start, o.end);
    const half = Math.max((hostOf(m, o)?.thickness ?? 0) / 2, tol);
    if (!a) { // along a diagonal wall
      if (lengthOf(o.start, o.end) <= EDIT.tolMm) continue;
      const f = frameOf(o.start, o.end);
      if (toS(f, p) >= -tol && toS(f, p) <= f.len + tol && Math.abs(toV(f, p)) <= half) return { kind: "opening", id: o.id };
      continue;
    }
    const [lo, hi] = span(a, o.start, o.end);
    if (along(a, p) >= lo - tol && along(a, p) <= hi + tol && Math.abs(cross(a, p) - cross(a, o.start)) <= half) return { kind: "opening", id: o.id };
  }
  for (const w of m.walls) {
    const a = axisOf(w.start, w.end);
    if (!a) {
      if (lengthOf(w.start, w.end) <= EDIT.tolMm) continue;
      const f = frameOf(w.start, w.end);
      if (toS(f, p) >= -tol && toS(f, p) <= f.len + tol && Math.abs(toV(f, p)) <= w.thickness / 2 + tol) return { kind: "wall", id: w.id };
      continue;
    }
    const [lo, hi] = span(a, w.start, w.end);
    if (along(a, p) >= lo - tol && along(a, p) <= hi + tol && Math.abs(cross(a, p) - cross(a, w.start)) <= w.thickness / 2 + tol) return { kind: "wall", id: w.id };
  }
  const r = m.rooms.find((x) => pointInPolygon(p, x.polygon));
  return r ? { kind: "room", id: r.id } : null;
}

/** Whether the pointer moved far enough from where it went down to count as a drag (screen px, via the scale). */
export const dragged = (origin: Pt, cur: Pt, scale: number) => Math.hypot(cur[0] - origin[0], cur[1] - origin[1]) * scale >= EDIT.dragMinPx;

/** Snap a wall move by whichever end snaps nearest (to another wall or the grid); returns the delta to move by. */
export function snapMove(w: EditWall, d: Pt, m: EditModel, scale: number): Pt {
  const best = [w.start, w.end].map((e) => {
    const t: Pt = [e[0] + d[0], e[1] + d[1]];
    const s = snap(t, m, scale, w.id);
    return { delta: [s[0] - e[0], s[1] - e[1]] as Pt, off: Math.hypot(s[0] - t[0], s[1] - t[1]) };
  }).sort((a, b) => a.off - b.off)[0];
  return best.delta;
}

/** An op that leaves its target exactly as it was (a click that moved nothing): not worth an edit. */
export function isNoop(op: EditOp): boolean {
  const same = (a: Pt, b: Pt) => near(a, b);
  if (op.op === "set_wall") return same(op.start, op.target.start) && same(op.end, op.target.end) && Math.abs(op.thickness - op.target.thickness) <= EDIT.tolMm;
  if (op.op === "set_opening") return op.kind === op.target.kind && same(op.start, op.target.start) && same(op.end, op.target.end) && op.height === undefined && op.sill_height === undefined;
  return false;
}

/** Which end of a wall is within `tol` of `p`, if any (the endpoint drag handles). */
export function endpointAt(w: EditWall, p: Pt, tol: number): "start" | "end" | null {
  const d = (q: Pt) => Math.hypot(q[0] - p[0], q[1] - p[1]);
  const [ds, de] = [d(w.start), d(w.end)];
  if (Math.min(ds, de) > tol) return null;
  return ds <= de ? "start" : "end";
}

// --- snap ----------------------------------------------------------------------------------------------------------
/** The 10 mm grid, then other walls' endpoints/axes within 8 px (x and y snap on their own). `skip` = a wall being dragged. */
export function snap(p: Pt, m: EditModel, scale: number, skip?: string): Pt {
  const r = pxToMm(EDIT.snapPx, scale);
  let onWall = false; // whether x or y snapped to another wall's endpoint (then that wins over a centreline)
  const pick = (v: number, cands: number[]) => {
    let best: number | null = null;
    for (const c of cands) if (Math.abs(c - v) <= r && (best === null || Math.abs(c - v) < Math.abs(best - v))) best = c;
    if (best !== null) onWall = true;
    return best ?? Math.round(v / EDIT.gridMm) * EDIT.gridMm;
  };
  const others = m.walls.filter((w) => w.id !== skip);
  const g: Pt = [pick(p[0], others.flatMap((w) => [w.start[0], w.end[0]])), pick(p[1], others.flatMap((w) => [w.start[1], w.end[1]]))];
  if (onWall) return g;
  // a diagonal wall's centreline is a snap target too, ahead of the grid (the axes of an angled wall are no use to x/y snapping)
  let best: Pt | null = null, off = r + 1;
  for (const w of others) {
    if (axisOf(w.start, w.end) || lengthOf(w.start, w.end) <= EDIT.tolMm) continue;
    const f = frameOf(w.start, w.end), s = Math.min(Math.max(toS(f, p), 0), f.len), q = atF(f, s), d = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (d <= r && d < off) { best = q; off = d; }
  }
  return best ?? g;
}

/** How a wall being drawn or dragged is turned: `ortho` onto the dominant axis, 15 or 45 degree steps, or free. */
export type AngleMode = "ortho" | "snap15" | "snap45" | "free";
export const ANGLE_MODES: { mode: AngleMode; label: string }[] = [
  { mode: "ortho", label: "Orthogonal" }, { mode: "snap15", label: "15° steps" }, { mode: "snap45", label: "45° steps" }, { mode: "free", label: "Free angle" },
];
export const orthogonal = (anchor: Pt, p: Pt): Pt => (Math.abs(p[0] - anchor[0]) >= Math.abs(p[1] - anchor[1]) ? [p[0], anchor[1]] : [anchor[0], p[1]]);

/** The end `p` of a wall from `anchor`, under the angle mode. Stepped angles keep the direction and put the
 *  dominant coordinate on the grid (so a 45 degree wall from the origin ends at (2000, 2000), not at a length). */
export function constrain(anchor: Pt, p: Pt, mode: AngleMode): Pt {
  if (mode === "ortho") return orthogonal(anchor, p);
  if (mode === "free") return p;
  if (lengthOf(anchor, p) === 0) return p;
  const rad = (Math.round(angleDeg(anchor, p) / (mode === "snap15" ? 15 : 45)) * (mode === "snap15" ? 15 : 45) * Math.PI) / 180;
  const c = Math.cos(rad), sn = Math.sin(rad), grid = (v: number) => Math.round(v / EDIT.gridMm) * EDIT.gridMm, tidy = (v: number) => Math.round(v * 1e6) / 1e6;
  if (Math.abs(c) >= Math.abs(sn)) {
    const x = grid(p[0]);
    return [x, tidy(anchor[1] + ((x - anchor[0]) * sn) / c)];
  }
  const y = grid(p[1]);
  return [tidy(anchor[0] + ((y - anchor[1]) * c) / sn), y];
}

// --- drag handles ----------------------------------------------------------------------------------------------------
export type Geom = { start: Pt; end: Pt };

/** Wall body: the whole wall moves by `d`. */
export const moveWall = (w: EditWall, d: Pt): Geom => ({ start: [w.start[0] + d[0], w.start[1] + d[1]], end: [w.end[0] + d[0], w.end[1] + d[1]] });

/** Wall end: only the length along the axis changes. Null when it would be shorter than the minimum. */
export function dragEndpoint(w: EditWall, which: "start" | "end", p: Pt, mode: AngleMode = "ortho"): Geom | null {
  const a = axisOf(w.start, w.end);
  const fixed = which === "start" ? w.end : w.start;
  let moved: Pt;
  if (mode !== "ortho") moved = constrain(fixed, p, mode); // turning the wall: the angle mode decides
  else if (a) moved = at(a, along(a, p), cross(a, w.start));
  else { // a diagonal wall in orthogonal mode keeps its direction: only the length changes
    if (lengthOf(w.start, w.end) <= EDIT.tolMm) return null;
    const f = frameOf(fixed, which === "start" ? w.start : w.end);
    moved = atF(f, toS(f, p));
  }
  const g = which === "start" ? { start: moved, end: w.end } : { start: w.start, end: moved };
  return lengthOf(g.start, g.end) >= EDIT.minWallMm ? g : null;
}

/** Opening: slides along its host wall (clamped to the host's span), width unchanged. */
export function slideOpening(o: EditOpening, host: EditWall, d: Pt): Geom | null {
  const a = axisOf(o.start, o.end);
  const ha = axisOf(host.start, host.end);
  if (!a && !ha) { // along a diagonal host
    if (!parallel(o.start, o.end, host.start, host.end)) return null;
    const f = frameOf(host.start, host.end);
    const [s0, s1] = [toS(f, o.start), toS(f, o.end)].sort((x, y) => x - y);
    const shift = Math.min(Math.max(d[0] * f.u[0] + d[1] * f.u[1], -s0), f.len - s1);
    return { start: [o.start[0] + f.u[0] * shift, o.start[1] + f.u[1] * shift], end: [o.end[0] + f.u[0] * shift, o.end[1] + f.u[1] * shift] };
  }
  if (!a || a !== ha) return null;
  const [lo, hi] = span(a, o.start, o.end), [hlo, hhi] = span(a, host.start, host.end);
  const shift = Math.min(Math.max(along(a, d), hlo - lo), hhi - hi);
  const c = cross(a, o.start);
  return { start: at(a, along(a, o.start) + shift, c), end: at(a, along(a, o.end) + shift, c) };
}

// --- op builders (capture the target snapshot) -----------------------------------------------------------------------
export const wallRef = (w: EditWall): WallRef => ({ start: w.start, end: w.end, thickness: w.thickness, handles: w.handles });
export const openingRef = (o: EditOpening): OpeningRef => ({ kind: o.kind, start: o.start, end: o.end, handles: o.handles });

/** `e<N+1>`: ids are chosen by the client and must be unique among the floor's edits. */
export function nextId(ops: { id: string }[]): string {
  const n = Math.max(0, ...ops.map((o) => Number(/^e(\d+)$/.exec(o.id)?.[1] ?? 0)));
  return `e${n + 1}`;
}

export const setWallOp = (id: string, w: EditWall, g: Geom, thickness = w.thickness): EditOp | null =>
  lengthOf(g.start, g.end) > EDIT.tolMm && thickness > 0 ? { op: "set_wall", id, target: wallRef(w), start: g.start, end: g.end, thickness } : null;
export const addWallOp = (id: string, start: Pt, end: Pt, thickness: number = EDIT.defaultThicknessMm): EditOp | null =>
  lengthOf(start, end) >= EDIT.minWallMm && thickness > 0 ? { op: "add_wall", id, start, end, thickness } : null;
export const removeWallOp = (id: string, w: EditWall): EditOp => ({ op: "remove_wall", id, target: wallRef(w) });
export const setOpeningOp = (id: string, o: EditOpening, patch: Partial<Geom> & { kind?: Kind } & Dims = {}): EditOp => ({
  op: "set_opening", id, target: openingRef(o), kind: patch.kind ?? o.kind, start: patch.start ?? o.start, end: patch.end ?? o.end,
  ...(patch.height === undefined ? {} : { height: patch.height }), ...(patch.sill_height === undefined ? {} : { sill_height: patch.sill_height }),
});
export const removeOpeningOp = (id: string, o: EditOpening): EditOp => ({ op: "remove_opening", id, target: openingRef(o) });
export const renameRoomOp = (id: string, r: EditRoom, name: string): EditOp | null =>
  name.trim() ? { op: "rename_room", id, point: r.label_point, name: name.trim() } : null;

/** Opening drawn by dragging along `host` from `a` to `b` (plan mm): snapped to the grid, clamped to the wall and to the
 *  free gap (between the host's other openings) that holds the press point; null when shorter than the minimum. */
export function dragOpeningOp(id: string, host: EditWall, kind: Kind, a: Pt, b: Pt, others: EditOpening[], dims: Dims = {}): EditOp | null {
  const ax = axisOf(host.start, host.end);
  const g = (v: number) => Math.round(v / EDIT.gridMm) * EDIT.gridMm;
  if (!ax) { // along a diagonal wall: the offset from its start, on the grid
    if (lengthOf(host.start, host.end) <= EDIT.tolMm) return null;
    const f = frameOf(host.start, host.end);
    let [lo, hi] = [0, f.len];
    const press = toS(f, a);
    for (const o of others.filter((x) => x.wall_id === host.id)) {
      const [olo, ohi] = [toS(f, o.start), toS(f, o.end)].sort((x, y) => x - y);
      if (press >= olo - EDIT.tolMm && press <= ohi + EDIT.tolMm) return null; // pressed on an opening
      if (ohi <= press) lo = Math.max(lo, ohi);
      else if (olo >= press) hi = Math.min(hi, olo);
    }
    const [sa, sb] = [g(toS(f, a)), g(toS(f, b))].sort((x, y) => x - y);
    const [s, e] = [Math.min(Math.max(sa, lo), hi), Math.min(Math.max(sb, lo), hi)];
    if (e - s < EDIT.minOpeningMm) return null;
    const [start, end] = lowYFirst(atF(f, s), atF(f, e));
    return { op: "add_opening", id, wall: wallRef(host), kind, start, end, ...dims };
  }
  let [lo, hi] = span(ax, host.start, host.end);
  const press = along(ax, a);
  for (const o of others.filter((x) => x.wall_id === host.id)) {
    const [olo, ohi] = span(ax, o.start, o.end);
    if (press >= olo - EDIT.tolMm && press <= ohi + EDIT.tolMm) return null; // pressed on an opening
    if (ohi <= press) lo = Math.max(lo, ohi);
    else if (olo >= press) hi = Math.min(hi, olo);
  }
  const s = Math.min(Math.max(Math.min(g(along(ax, a)), g(along(ax, b))), lo), hi);
  const e = Math.min(Math.max(Math.max(g(along(ax, a)), g(along(ax, b))), lo), hi);
  if (e - s < EDIT.minOpeningMm) return null;
  const c = cross(ax, host.start);
  return { op: "add_opening", id, wall: wallRef(host), kind, start: at(ax, s, c), end: at(ax, e, c), ...dims };
}

/** Height and sill fields of the tool (empty = the project's default, set by the server). Door sill is always 0. */
export function openingDims(kind: Kind, height: string, sill: string): Parsed<Dims> {
  const h = height.trim() === "" ? undefined : parse(height), s = sill.trim() === "" || kind === "door" ? undefined : parse(sill);
  if (h === null || s === null || (h !== undefined && !(h > 0)) || (s !== undefined && s < 0)) return { ok: false, error: "Height must be above 0 and the sill 0 or more." };
  return { ok: true, value: { ...(h === undefined ? {} : { height: h }), ...(kind === "door" ? { sill_height: 0 } : s === undefined ? {} : { sill_height: s }) } };
}

// --- undo / redo ---------------------------------------------------------------------------------------------------------
export type History = { done: EditOp[]; undone: EditOp[] };
export const EMPTY_HISTORY: History = { done: [], undone: [] };
export const canAdd = (existing: number, h: History) => existing + h.done.length < EDIT.maxEdits;
export const push = (h: History, op: EditOp): History => ({ done: [...h.done, op], undone: [] });
export const undo = (h: History): History => (h.done.length ? { done: h.done.slice(0, -1), undone: [...h.undone, h.done[h.done.length - 1]] } : h);
export const redo = (h: History): History => (h.undone.length ? { done: [...h.done, h.undone[h.undone.length - 1]], undone: h.undone.slice(0, -1) } : h);

// --- local preview -----------------------------------------------------------------------------------------------------------
const sameHandles = (a: string[], b: string[]) => a.some((h) => b.includes(h));
const matchWall = (m: EditModel, r: WallRef) => m.walls.find((w) => sameHandles(w.handles, r.handles) && near(w.start, r.start) && near(w.end, r.end));
const matchOpening = (m: EditModel, r: OpeningRef) => m.openings.find((o) => sameHandles(o.handles, r.handles) && near(o.start, r.start) && near(o.end, r.end));

/** The model after `ops`, as far as the edited rectangles go. Rooms are only renamed: their outlines change after saving. */
export function applyOps(base: EditModel, ops: EditOp[]): EditModel {
  let m: EditModel = { walls: [...base.walls], openings: [...base.openings], rooms: [...base.rooms] };
  for (const op of ops) {
    if (op.op === "set_wall") {
      const w = matchWall(m, op.target);
      if (!w) continue;
      const a = axisOf(w.start, w.end), na = axisOf(op.start, op.end);
      const edited = { ...w, start: op.start, end: op.end, thickness: op.thickness, handles: [op.id], provenance: Math.abs(op.thickness - w.thickness) > EDIT.tolMm ? "user_modified" : w.provenance };
      if (a && na) { // axis-aligned before and after
        const [lo] = span(a, w.start, w.end), [nlo, nhi] = span(na, op.start, op.end);
        const same = a === na && Math.abs(nhi - nlo - (span(a, w.start, w.end)[1] - lo)) <= EDIT.tolMm;
        m = {
          ...m,
          walls: m.walls.map((x) => (x === w ? edited : x)),
          openings: m.openings.flatMap((o) => { // openings travel with their wall, as on the server
            if (o.wall_id !== w.id) return [o];
            if (a !== na) return [];
            const [olo, ohi] = span(a, o.start, o.end), sh = same ? nlo - lo : 0;
            if (olo + sh < nlo - EDIT.tolMm || ohi + sh > nhi + EDIT.tolMm) return [];
            return [{ ...o, start: at(a, along(a, o.start) + sh, cross(a, op.start)), end: at(a, along(a, o.end) + sh, cross(a, op.start)) }];
          }),
        };
      } else { // a diagonal wall before or after: openings keep their offset (same length) or their place in the plan
        const f = frameOf(w.start, w.end), nf = frameOf(op.start, op.end);
        m = {
          ...m,
          walls: m.walls.map((x) => (x === w ? edited : x)),
          openings: m.openings.flatMap((o) => {
            if (o.wall_id !== w.id) return [o];
            let [s0, s1] = [toS(f, o.start), toS(f, o.end)].sort((x, y) => x - y);
            if (Math.abs(nf.len - f.len) > EDIT.tolMm) {
              const [p0, p1] = [atF(f, s0), atF(f, s1)];
              if (Math.abs(toV(nf, p0)) > EDIT.tolMm || Math.abs(toV(nf, p1)) > EDIT.tolMm) return [];
              [s0, s1] = [toS(nf, p0), toS(nf, p1)];
            }
            if (s0 < -EDIT.tolMm || s1 > nf.len + EDIT.tolMm) return [];
            const [start, end] = na ? [atF(nf, s0), atF(nf, s1)] as [Pt, Pt] : lowYFirst(atF(nf, s0), atF(nf, s1));
            return [{ ...o, start, end }];
          }),
        };
      }
    } else if (op.op === "add_wall") {
      m = { ...m, walls: [...m.walls, { id: `new-${op.id}`, start: op.start, end: op.end, thickness: op.thickness, handles: [op.id], provenance: "user_modified" }] };
    } else if (op.op === "remove_wall") {
      const w = matchWall(m, op.target);
      if (w) m = { ...m, walls: m.walls.filter((x) => x !== w), openings: m.openings.filter((o) => o.wall_id !== w.id) };
    } else if (op.op === "set_opening") {
      const o = matchOpening(m, op.target);
      if (o) m = { ...m, openings: m.openings.map((x) => (x === o ? { ...o, kind: op.kind, start: op.start, end: op.end, width: lengthOf(op.start, op.end), height: op.height ?? o.height, sill: op.sill_height ?? o.sill, handles: [op.id], provenance: "user_modified" } : x)) };
    } else if (op.op === "add_opening") {
      const host = matchWall(m, op.wall);
      m = { ...m, openings: [...m.openings, { id: `new-${op.id}`, kind: op.kind, start: op.start, end: op.end, wall_id: host?.id ?? "", width: lengthOf(op.start, op.end), height: op.height ?? null, sill: op.sill_height ?? null, provenance: "user_modified", handles: [op.id] }] };
    } else if (op.op === "remove_opening") {
      const o = matchOpening(m, op.target);
      if (o) m = { ...m, openings: m.openings.filter((x) => x !== o) };
    } else {
      const r = m.rooms.find((x) => pointInPolygon(op.point, x.polygon));
      if (r) m = { ...m, rooms: m.rooms.map((x) => (x === r ? { ...r, name: op.name, name_source: "user_modified" } : x)) };
    }
  }
  return m;
}

// --- inspector --------------------------------------------------------------------------------------------------------------
export type InspectorRow = { label: string; source: string; edited: string; changed: boolean };
const pt = (p: Pt) => `${Math.round(p[0] * 10) / 10}, ${Math.round(p[1] * 10) / 10}`;
const num = (v: number | null) => (v === null ? "default (set by the server)" : `${Math.round(v * 10) / 10}`);
const row = (label: string, source: string | undefined, edited: string): InspectorRow => ({ label, source: source ?? "(new)", edited, changed: source !== edited });

/** Source (the model the edits started from) next to edited (with the pending ops), per field of the selection. */
export function inspectorRows(base: EditModel, now: EditModel, sel: Selection): InspectorRow[] {
  if (sel.kind === "wall") {
    const [b, n] = [base.walls.find((w) => w.id === sel.id), now.walls.find((w) => w.id === sel.id)];
    const len = (w: EditWall) => num(lengthOf(w.start, w.end)), ang = (w: EditWall) => `${Math.round(angleDeg(w.start, w.end) * 100) / 100}°`;
    return n ? [row("Start (mm)", b && pt(b.start), pt(n.start)), row("End (mm)", b && pt(b.end), pt(n.end)), row("Length (mm)", b && len(b), len(n)), row("Angle", b && ang(b), ang(n)),
      row("Thickness (mm)", b && num(b.thickness), num(n.thickness))] : [];
  }
  if (sel.kind === "opening") {
    const [b, n] = [base.openings.find((o) => o.id === sel.id), now.openings.find((o) => o.id === sel.id)];
    if (!n) return [];
    const offset = (m: EditModel, o: EditOpening) => {
      const h = hostOf(m, o), a = axisOf(o.start, o.end);
      if (h && !a && lengthOf(h.start, h.end) > EDIT.tolMm) { const f = frameOf(h.start, h.end); return num(Math.min(toS(f, o.start), toS(f, o.end))); }
      return h && a ? num(span(a, o.start, o.end)[0] - span(a, h.start, h.end)[0]) : "?";
    };
    return [row("Kind", b?.kind, n.kind), row("Offset on wall (mm)", b && offset(base, b), offset(now, n)), row("Width (mm)", b && num(b.width), num(n.width)),
      row("Height (mm)", b && num(b.height), num(n.height)), row("Sill (mm)", b && num(b.sill), num(n.sill))];
  }
  const [b, n] = [base.rooms.find((r) => r.id === sel.id), now.rooms.find((r) => r.id === sel.id)];
  return n ? [row("Name", b?.name, n.name)] : [];
}

// --- inspector fields -> ops -----------------------------------------------------------------------------------------------------
const parse = (s: string) => (s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null);
export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

export function wallFromFields(f: { sx: string; sy: string; ex: string; ey: string; thickness: string }): Parsed<Geom & { thickness: number }> {
  const [sx, sy, ex, ey, t] = [f.sx, f.sy, f.ex, f.ey, f.thickness].map(parse);
  if ([sx, sy, ex, ey, t].some((v) => v === null)) return { ok: false, error: "Start, end and thickness must be numbers." };
  const g = { start: [sx!, sy!] as Pt, end: [ex!, ey!] as Pt };
  if (lengthOf(g.start, g.end) < EDIT.minWallMm) return { ok: false, error: `A wall is at least ${EDIT.minWallMm} mm long.` };
  if (!(t! > 0)) return { ok: false, error: "Thickness must be above 0." };
  return { ok: true, value: { ...g, thickness: t! } };
}

/** The inspector's other way to give a wall: its start, a length and an angle (degrees, counter-clockwise from +x). */
export function wallFromPolar(f: { sx: string; sy: string; length: string; angle: string; thickness: string }): Parsed<Geom & { thickness: number }> {
  const [sx, sy, len, ang, t] = [f.sx, f.sy, f.length, f.angle, f.thickness].map(parse);
  if ([sx, sy, len, ang, t].some((v) => v === null)) return { ok: false, error: "Start, length, angle and thickness must be numbers." };
  if (!(len! >= EDIT.minWallMm)) return { ok: false, error: `A wall is at least ${EDIT.minWallMm} mm long.` };
  if (!(t! > 0)) return { ok: false, error: "Thickness must be above 0." };
  const start: Pt = [sx!, sy!], end = polar(start, len!, ang!);
  return { ok: true, value: { start, end: [Math.round(end[0] * 1000) / 1000, Math.round(end[1] * 1000) / 1000], thickness: t! } };
}

export function openingFromFields(host: EditWall, f: { offset: string; width: string; height: string; sill: string }): Parsed<Geom & Dims> {
  const a = axisOf(host.start, host.end);
  const [off, w] = [parse(f.offset), parse(f.width)];
  const [h, s] = [f.height.trim() === "" ? undefined : parse(f.height), f.sill.trim() === "" ? undefined : parse(f.sill)];
  if (off === null || w === null || h === null || s === null || (!a && lengthOf(host.start, host.end) <= EDIT.tolMm)) return { ok: false, error: "Offset, width, height and sill must be numbers." };
  if (!a) { // a diagonal host: the offset runs along the wall from its start
    const fr = frameOf(host.start, host.end);
    if (!(w > 0) || off < 0 || off + w > fr.len + EDIT.tolMm) return { ok: false, error: "The opening must lie inside its wall." };
    if ((h !== undefined && !(h > 0)) || (s !== undefined && s < 0)) return { ok: false, error: "Height must be above 0 and the sill 0 or more." };
    const [start, end] = lowYFirst(atF(fr, off), atF(fr, off + w));
    return { ok: true, value: { start, end, ...(h === undefined ? {} : { height: h }), ...(s === undefined ? {} : { sill_height: s }) } };
  }
  const [lo, hi] = span(a, host.start, host.end);
  if (!(w > 0) || off < 0 || lo + off + w > hi + EDIT.tolMm) return { ok: false, error: "The opening must lie inside its wall." };
  if ((h !== undefined && !(h > 0)) || (s !== undefined && s < 0)) return { ok: false, error: "Height must be above 0 and the sill 0 or more." };
  const c = cross(a, host.start);
  return { ok: true, value: { start: at(a, lo + off, c), end: at(a, lo + off + w, c), ...(h === undefined ? {} : { height: h }), ...(s === undefined ? {} : { sill_height: s }) } };
}
