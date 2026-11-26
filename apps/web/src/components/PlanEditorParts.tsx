"use client";

import { useState } from "react";
import {
  ANGLE_MODES, EDIT, angleDeg, frameOf, inspectorRows, nextId, openingFromFields, removeOpeningOp, removeWallOp, renameRoomOp, setOpeningOp, setWallOp, toS, wallFromFields, wallFromPolar,
  type AngleMode, type EditModel, type EditOp, type InspectorRow, type Kind, type Selection,
} from "../lib/plan-edit";

export type Tool = "select" | "wall" | "door" | "window" | "delete";
const TOOLS: { id: Tool; label: string; hint: string }[] = [
  { id: "select", label: "Select / move", hint: "Click to select; drag a wall to move it, drag a wall end to change its length (or its angle, in an angle mode), drag an opening along its wall; drag empty space to pan; wheel to zoom." },
  { id: "wall", label: "Add wall", hint: "Click the start, then the end. The angle mode decides the direction: orthogonal, 15 or 45 degree steps, or free." },
  { id: "door", label: "Add door", hint: "Press on a wall, drag along it and release: the door spans the dragged length." },
  { id: "window", label: "Add window", hint: "Press on a wall, drag along it and release: the window spans the dragged length." },
  { id: "delete", label: "Delete", hint: "Click a wall or an opening to remove it (a wall takes its openings with it)." },
];

export function EditorToolbar(p: {
  tool: Tool; setTool: (t: Tool) => void;
  height: string; setHeight: (s: string) => void; sill: string; setSill: (s: string) => void; thickness: string; setThickness: (s: string) => void; mode: AngleMode; setMode: (m: AngleMode) => void;
  canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void;
  pending: number; busy: boolean; onSave: () => void; onDiscard: () => void;
}) {
  const hint = TOOLS.find((t) => t.id === p.tool)!.hint;
  return (
    <div role="toolbar" aria-label="Plan editing tools">
      {TOOLS.map((t) => (
        <button key={t.id} type="button" aria-pressed={p.tool === t.id} onClick={() => p.setTool(t.id)}>{t.label}</button>
      ))}{" "}
      {(p.tool === "wall" || p.tool === "select") && (
        <label>Wall angle <select aria-label="Wall angle mode" value={p.mode} onChange={(e) => p.setMode(e.target.value as AngleMode)}>
          {ANGLE_MODES.map((m) => <option key={m.mode} value={m.mode}>{m.label}</option>)}
        </select>{" "}</label>
      )}
      {p.tool === "wall" && (
        <label>Thickness (mm) <input aria-label="New wall thickness" inputMode="decimal" value={p.thickness} onChange={(e) => p.setThickness(e.target.value)} size={5} /></label>
      )}
      {(p.tool === "door" || p.tool === "window") && (
        <>
          <label>{p.tool === "door" ? "Door" : "Window"} height (mm) <input aria-label="New opening height" inputMode="decimal" value={p.height} placeholder="project default" onChange={(e) => p.setHeight(e.target.value)} size={8} /></label>{" "}
          {p.tool === "window" && <label>Sill above floor (mm) <input aria-label="New window sill" inputMode="decimal" value={p.sill} placeholder="project default" onChange={(e) => p.setSill(e.target.value)} size={8} /></label>}{" "}
          <small>A click is not enough: press on a wall and drag along it to draw the {p.tool}. Empty fields use the project default; values you enter are marked as yours.</small>
        </>
      )}
      <p><small>{hint}</small></p>
      <button type="button" disabled={!p.canUndo || p.busy} onClick={p.onUndo}>Undo</button>{" "}
      <button type="button" disabled={!p.canRedo || p.busy} onClick={p.onRedo}>Redo</button>{" "}
      <button type="button" disabled={p.pending === 0 || p.busy} onClick={p.onSave}>Save {p.pending > 0 ? `(${p.pending} change${p.pending === 1 ? "" : "s"})` : ""}</button>{" "}
      <button type="button" disabled={p.pending === 0 || p.busy} onClick={p.onDiscard}>Discard</button>
    </div>
  );
}

const fieldRow = (label: string, value: string, set: (s: string) => void) => (
  <label key={label} style={{ display: "block", margin: "4px 0" }}>{label} <input aria-label={label} inputMode="decimal" value={value} onChange={(e) => set(e.target.value)} size={9} /></label>
);

/** The selected element: source vs edited columns, numeric fields and the delete button. Every Apply is one op. */
export function PlanInspector(p: {
  base: EditModel; committed: EditModel; now: EditModel; sel: Selection | null; allOps: { id: string }[];
  onOp: (op: EditOp) => void; disabled?: boolean;
}) {
  const { sel, committed } = p;
  const [error, setError] = useState<string | null>(null);
  if (!sel) return <aside aria-label="Inspector"><p>Select a wall, opening or room to see and change its values.</p></aside>;
  const rows: InspectorRow[] = inspectorRows(p.base, p.now, sel);
  const id = nextId(p.allOps);
  const wall = sel.kind === "wall" ? committed.walls.find((w) => w.id === sel.id) : undefined;
  const opening = sel.kind === "opening" ? committed.openings.find((o) => o.id === sel.id) : undefined;
  const room = sel.kind === "room" ? committed.rooms.find((r) => r.id === sel.id) : undefined;
  const key = `${sel.kind}:${sel.id}:${p.allOps.length}`; // fields start again from the model after every change
  return (
    <aside aria-label="Inspector">
      <h3>{sel.kind} <code>{sel.id}</code></h3>
      <table>
        <thead><tr><th>Field</th><th>Source</th><th>Edited</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} style={r.changed ? { fontWeight: 600 } : undefined}>
              <td>{r.label}</td><td>{r.source}</td><td>{r.edited}{r.changed ? " (changed)" : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!p.disabled && (
        <div key={key}>
          {wall && <WallFields wall={wall} onApply={(w) => {
            const r = "length" in w ? wallFromPolar(w) : wallFromFields(w);
            if (!r.ok) return setError(r.error);
            const op = setWallOp(id, wall, r.value, r.value.thickness);
            if (!op) return setError("A wall needs a length.");
            setError(null);
            p.onOp(op);
          }} onDelete={() => p.onOp(removeWallOp(id, wall))} />}
          {opening && <OpeningFields o={opening} host={committed.walls.find((w) => w.id === opening.wall_id)} onApply={(f, kind) => {
            const host = committed.walls.find((w) => w.id === opening.wall_id);
            const r = host ? openingFromFields(host, f) : ({ ok: false, error: "The opening's wall is not known." } as const);
            if (!r.ok) return setError(r.error);
            setError(null);
            p.onOp(setOpeningOp(id, opening, { ...r.value, kind }));
          }} onDelete={() => p.onOp(removeOpeningOp(id, opening))} />}
          {room && <RoomField name={room.name} onApply={(n) => {
            const op = renameRoomOp(id, room, n);
            if (!op) return setError("A room name cannot be empty.");
            setError(null);
            p.onOp(op);
          }} />}
        </div>
      )}
      {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
    </aside>
  );
}

type WallPoints = { sx: string; sy: string; ex: string; ey: string; thickness: string };
type WallPolar = { sx: string; sy: string; length: string; angle: string; thickness: string };

function WallFields(p: { wall: EditModel["walls"][number]; onApply: (f: WallPoints | WallPolar) => void; onDelete: () => void }) {
  const w = p.wall;
  const [f, setF] = useState({ sx: String(w.start[0]), sy: String(w.start[1]), ex: String(w.end[0]), ey: String(w.end[1]), thickness: String(w.thickness) });
  const [g, setG] = useState({ length: String(Math.round(Math.hypot(w.end[0] - w.start[0], w.end[1] - w.start[1]) * 100) / 100), angle: String(Math.round(angleDeg(w.start, w.end) * 100) / 100) });
  const set = (k: keyof typeof f) => (s: string) => setF({ ...f, [k]: s });
  return (
    <>
      {fieldRow("Start x (mm)", f.sx, set("sx"))}{fieldRow("Start y (mm)", f.sy, set("sy"))}
      {fieldRow("End x (mm)", f.ex, set("ex"))}{fieldRow("End y (mm)", f.ey, set("ey"))}
      {fieldRow("Thickness (mm)", f.thickness, set("thickness"))}
      <button type="button" onClick={() => p.onApply(f)}>Apply</button>{" "}
      <fieldset style={{ margin: "6px 0" }}>
        <legend>Or by length and angle from the start</legend>
        {fieldRow("Length (mm)", g.length, (s) => setG({ ...g, length: s }))}{fieldRow("Angle (degrees, from +x)", g.angle, (s) => setG({ ...g, angle: s }))}
        <button type="button" onClick={() => p.onApply({ sx: f.sx, sy: f.sy, thickness: f.thickness, ...g })}>Apply length and angle</button>
      </fieldset>
      <button type="button" onClick={p.onDelete}>Delete wall</button>
    </>
  );
}

function OpeningFields(p: { o: EditModel["openings"][number]; host?: EditModel["walls"][number]; onApply: (f: { offset: string; width: string; height: string; sill: string }, kind: Kind) => void; onDelete: () => void }) {
  const { o, host } = p;
  const horiz = Math.abs(o.end[1] - o.start[1]) <= EDIT.tolMm;
  const vert = Math.abs(o.end[0] - o.start[0]) <= EDIT.tolMm;
  const fr = !horiz && !vert && host ? frameOf(host.start, host.end) : null; // a diagonal host: offsets run along it from its start
  const lo = (pt: [number, number]) => (fr ? toS(fr, pt) : horiz ? pt[0] : pt[1]);
  const hostLo = host && !fr ? Math.min(lo(host.start), lo(host.end)) : 0;
  const [kind, setKind] = useState<Kind>(o.kind);
  const [f, setF] = useState({ offset: String(Math.round((Math.min(lo(o.start), lo(o.end)) - hostLo) * 100) / 100), width: String(o.width), height: o.height === null ? "" : String(o.height), sill: o.sill === null ? "" : String(o.sill) });
  const set = (k: keyof typeof f) => (s: string) => setF({ ...f, [k]: s });
  return (
    <>
      <label style={{ display: "block", margin: "4px 0" }}>Kind{" "}
        <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value as Kind)}><option value="door">door</option><option value="window">window</option></select>
      </label>
      {fieldRow("Offset on wall (mm)", f.offset, set("offset"))}{fieldRow("Width (mm)", f.width, set("width"))}
      {fieldRow("Height (mm)", f.height, set("height"))}{fieldRow("Sill (mm)", f.sill, set("sill"))}
      <small>Leave height or sill empty to keep the current value.</small><br />
      <button type="button" onClick={() => p.onApply(f, kind)}>Apply</button>{" "}
      <button type="button" onClick={p.onDelete}>Delete opening</button>
    </>
  );
}

function RoomField(p: { name: string; onApply: (n: string) => void }) {
  const [n, setN] = useState(p.name);
  return (
    <>
      <label style={{ display: "block", margin: "4px 0" }}>Room name <input aria-label="Room name" value={n} maxLength={100} onChange={(e) => setN(e.target.value)} /></label>
      <button type="button" onClick={() => p.onApply(n)}>Rename</button>
    </>
  );
}
