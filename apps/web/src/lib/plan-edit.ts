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
    if (!a) continue;
    const [lo, hi] = span(a, o.start, o.end);
    const half = Math.max((hostOf(m, o)?.thickness ?? 0) / 2, tol);
    if (along(a, p) >= lo - tol && along(a, p) <= hi + tol && Math.abs(cross(a, p) - cross(a, o.start)) <= half) return { kind: "opening", id: o.id };
  }
  for (const w of m.walls) {
    const a = axisOf(w.start, w.end);
    if (!a) continue;
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
  const pick = (v: number, cands: number[]) => {
    let best: number | null = null;
    for (const c of cands) if (Math.abs(c - v) <= r && (best === null || Math.abs(c - v) < Math.abs(best - v))) best = c;
    return best ?? Math.round(v / EDIT.gridMm) * EDIT.gridMm;
  };
  const others = m.walls.filter((w) => w.id !== skip);
  return [pick(p[0], others.flatMap((w) => [w.start[0], w.end[0]])), pick(p[1], others.flatMap((w) => [w.start[1], w.end[1]]))];
}

/** Force the segment anchor -> p onto the dominant axis (orthogonal walls only). */
export const orthogonal = (anchor: Pt, p: Pt): Pt => (Math.abs(p[0] - anchor[0]) >= Math.abs(p[1] - anchor[1]) ? [p[0], anchor[1]] : [anchor[0], p[1]]);

// --- drag handles ----------------------------------------------------------------------------------------------------
export type Geom = { start: Pt; end: Pt };

/** Wall body: the whole wall moves by `d`. */
export const moveWall = (w: EditWall, d: Pt): Geom => ({ start: [w.start[0] + d[0], w.start[1] + d[1]], end: [w.end[0] + d[0], w.end[1] + d[1]] });

/** Wall end: only the length along the axis changes. Null when it would be shorter than the minimum. */
export function dragEndpoint(w: EditWall, which: "start" | "end", p: Pt): Geom | null {
  const a = axisOf(w.start, w.end);
  if (!a) return null;
  const moved = at(a, along(a, p), cross(a, w.start));
  const g = which === "start" ? { start: moved, end: w.end } : { start: w.start, end: moved };
  return lengthOf(g.start, g.end) >= EDIT.minWallMm ? g : null;
}

/** Opening: slides along its host wall (clamped to the host's span), width unchanged. */
export function slideOpening(o: EditOpening, host: EditWall, d: Pt): Geom | null {
  const a = axisOf(o.start, o.end);
  const ha = axisOf(host.start, host.end);
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
  axisOf(g.start, g.end) && thickness > 0 ? { op: "set_wall", id, target: wallRef(w), start: g.start, end: g.end, thickness } : null;
export const addWallOp = (id: string, start: Pt, end: Pt, thickness: number = EDIT.defaultThicknessMm): EditOp | null =>
  axisOf(start, end) && lengthOf(start, end) >= EDIT.minWallMm && thickness > 0 ? { op: "add_wall", id, start, end, thickness } : null;
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
  if (!ax) return null;
  const g = (v: number) => Math.round(v / EDIT.gridMm) * EDIT.gridMm;
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
      const [lo] = a ? span(a, w.start, w.end) : [0], [nlo, nhi] = na ? span(na, op.start, op.end) : [0, 0];
      const same = a !== null && a === na && Math.abs(nhi - nlo - (span(a, w.start, w.end)[1] - lo)) <= EDIT.tolMm;
      const edited = { ...w, start: op.start, end: op.end, thickness: op.thickness, handles: [op.id], provenance: Math.abs(op.thickness - w.thickness) > EDIT.tolMm ? "user_modified" : w.provenance };
      m = {
        ...m,
        walls: m.walls.map((x) => (x === w ? edited : x)),
        openings: m.openings.flatMap((o) => { // openings travel with their wall, as on the server
          if (o.wall_id !== w.id) return [o];
          if (!a || a !== na) return [];
          const [olo, ohi] = span(a, o.start, o.end), sh = same ? nlo - lo : 0;
          if (olo + sh < nlo - EDIT.tolMm || ohi + sh > nhi + EDIT.tolMm) return [];
          return [{ ...o, start: at(a, along(a, o.start) + sh, cross(a, op.start)), end: at(a, along(a, o.end) + sh, cross(a, op.start)) }];
        }),
      };
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
    return n ? [row("Start (mm)", b && pt(b.start), pt(n.start)), row("End (mm)", b && pt(b.end), pt(n.end)), row("Thickness (mm)", b && num(b.thickness), num(n.thickness))] : [];
  }
  if (sel.kind === "opening") {
    const [b, n] = [base.openings.find((o) => o.id === sel.id), now.openings.find((o) => o.id === sel.id)];
    if (!n) return [];
    const offset = (m: EditModel, o: EditOpening) => {
      const h = hostOf(m, o), a = axisOf(o.start, o.end);
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
  if (!axisOf(g.start, g.end)) return { ok: false, error: "A wall must be horizontal or vertical (the start and end share x or y) and have a length." };
  if (lengthOf(g.start, g.end) < EDIT.minWallMm) return { ok: false, error: `A wall is at least ${EDIT.minWallMm} mm long.` };
  if (!(t! > 0)) return { ok: false, error: "Thickness must be above 0." };
  return { ok: true, value: { ...g, thickness: t! } };
}

export function openingFromFields(host: EditWall, f: { offset: string; width: string; height: string; sill: string }): Parsed<Geom & Dims> {
  const a = axisOf(host.start, host.end);
  const [off, w] = [parse(f.offset), parse(f.width)];
  const [h, s] = [f.height.trim() === "" ? undefined : parse(f.height), f.sill.trim() === "" ? undefined : parse(f.sill)];
  if (!a || off === null || w === null || h === null || s === null) return { ok: false, error: "Offset, width, height and sill must be numbers." };
  const [lo, hi] = span(a, host.start, host.end);
  if (!(w > 0) || off < 0 || lo + off + w > hi + EDIT.tolMm) return { ok: false, error: "The opening must lie inside its wall." };
  if ((h !== undefined && !(h > 0)) || (s !== undefined && s < 0)) return { ok: false, error: "Height must be above 0 and the sill 0 or more." };
  const c = cross(a, host.start);
  return { ok: true, value: { start: at(a, lo + off, c), end: at(a, lo + off + w, c), ...(h === undefined ? {} : { height: h }), ...(s === undefined ? {} : { sill_height: s }) } };
}
