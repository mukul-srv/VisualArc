"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import type { Issue } from "../lib/api";
import { saveEditsJob, STAGE_LABEL, type JobProgress } from "../lib/jobs";
import { fit, getPlanOverlay, overlayBounds, panBy, toPlan, toScreen, wallCorners, zoomAt, type Fit, type OverlayData } from "../lib/overlay";
import type { Floor } from "../lib/project";
import {
  EDIT, EMPTY_HISTORY, addWallOp, dragOpeningOp, openingDims, applyOps, canAdd, dragEndpoint, dragged, isNoop, snapMove, endpointAt, hitTest, moveWall, nextId, orthogonal, push, pxToMm, redo,
  removeOpeningOp, removeWallOp, setOpeningOp, setWallOp, slideOpening, snap, toEditModel, undo, type EditModel, type EditOp, type EditOpening, type EditWall, type Pt, type Selection,
} from "../lib/plan-edit";
import { IssueList } from "./IssueList";
import { UnderlayPanel, type Calibrating } from "./UnderlayPanel";
import { API_BASE } from "../lib/api";
import { calibrationScale, imageRect, planToPx, putCalibration, pxToPlan } from "../lib/underlay";
import { EditorToolbar, PlanInspector, type Tool } from "./PlanEditorParts";

const W = 720;
const H = 520;
type Drag =
  | { kind: "move" | "start" | "end"; wall: EditWall; origin: Pt; cur: Pt }
  | { kind: "slide"; opening: EditOpening; host: EditWall; origin: Pt; cur: Pt }
  | { kind: "draw"; host: EditWall; open: "door" | "window"; dims: { height?: number; sill_height?: number }; origin: Pt; cur: Pt }
  | { kind: "pan"; last: [number, number] };

/** The transient op of a drag, from the committed model: the same op that is saved when the pointer is released. */
function dragOp(d: Drag, committed: EditModel, id: string, scale: number): EditOp | null {
  if (d.kind === "pan" || !dragged(d.origin, d.cur, scale)) return null; // a click is not a drag: nothing is snapped or saved
  if (d.kind === "draw") return dragOpeningOp(id, d.host, d.open, d.origin, d.cur, committed.openings, d.dims);
  if (d.kind === "slide") {
    const g = slideOpening(d.opening, d.host, [d.cur[0] - d.origin[0], d.cur[1] - d.origin[1]]);
    return g && setOpeningOp(id, d.opening, g);
  }
  if (d.kind === "move") {
    return setWallOp(id, d.wall, moveWall(d.wall, snapMove(d.wall, [d.cur[0] - d.origin[0], d.cur[1] - d.origin[1]], committed, scale)));
  }
  const g = dragEndpoint(d.wall, d.kind, snap(d.cur, committed, scale, d.wall.id));
  return g && setWallOp(id, d.wall, g);
}

/** 2D plan editor for one floor: walls, doors/windows and room names. The server re-derives everything on save. */
export function PlanEditor({ projectId, floor, onSaved, onClose }: { projectId: string; floor: Floor; onSaved: () => void; onClose: () => void }) {
  const [data, setData] = useState<OverlayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hist, setHist] = useState(EMPTY_HISTORY);
  const [tool, setTool] = useState<Tool>("select");
  const [sel, setSel] = useState<Selection | null>(null);
  const [view, setView] = useState<Fit | null>(null);
  const [anchor, setAnchor] = useState<Pt | null>(null);
  const [hover, setHover] = useState<Pt | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [height, setHeight] = useState("");
  const [sill, setSill] = useState("");
  const [thickness, setThickness] = useState(String(EDIT.defaultThicknessMm));
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobProgress | null>(null);
  const [blocked, setBlocked] = useState<Issue[] | null>(null);
  const [saved, setSaved] = useState<Issue[] | null>(null); // issues of the last successful save (skipped edits show here)
  const canvas = useRef<HTMLCanvasElement>(null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [opacity, setOpacity] = useState(0.5);
  const [hideImg, setHideImg] = useState(false);
  const [locked, setLocked] = useState(true);
  const [calib, setCalib] = useState<Calibrating | null>(null);
  const [calibError, setCalibError] = useState<string | null>(null);
  const under = data?.underlay ?? null;
  const needsScale = under !== null && under.calibration === null; // nothing can be traced before the scale is known

  const load = useCallback(async () => {
    const r = await getPlanOverlay(projectId, floor.id);
    if (!r.ok) return setError(r.message);
    setError(null);
    setData(r.overlay);
    let b = overlayBounds(r.overlay);
    if (r.overlay.underlay) {
      const q = imageRect(r.overlay.underlay);
      b = b ? { minX: Math.min(b.minX, q.x0), minY: Math.min(b.minY, q.y0), maxX: Math.max(b.maxX, q.x1), maxY: Math.max(b.maxY, q.y1) } : { minX: q.x0, minY: q.y0, maxX: q.x1, maxY: q.y1 };
    }
    if (b) setView(fit(b, W, H));
  }, [projectId, floor.id]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  const base = useMemo(() => (data ? toEditModel(data) : null), [data]);
  const existing = useMemo(() => (data?.edits ?? []) as EditOp[], [data]);
  const allOps = useMemo(() => [...existing, ...hist.done], [existing, hist.done]);
  const committed = useMemo(() => (base ? applyOps(base, hist.done) : null), [base, hist.done]);
  const transient = drag && committed && view ? dragOp(drag, committed, nextId(allOps), view.scale) : null;
  const now = useMemo(() => (committed ? (transient ? applyOps(committed, [transient]) : committed) : null), [committed, transient]);

  const commit = useCallback((op: EditOp | null) => {
    if (op && !isNoop(op) && canAdd(existing.length, hist)) setHist(push(hist, op));
  }, [existing.length, hist]);

  // wheel zoom needs a non-passive listener so the page does not scroll
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = c.getBoundingClientRect();
      setView((v) => v && zoomAt(v, ((e.clientX - r.left) * W) / r.width, ((e.clientY - r.top) * H) / r.height, e.deltaY < 0 ? 1.15 : 1 / 1.15));
    };
    c.addEventListener("wheel", onWheel, { passive: false });
    return () => c.removeEventListener("wheel", onWheel);
  }, [data]);

  const underUrl = under?.url;
  useEffect(() => {
    if (!underUrl) return queueMicrotask(() => setImg(null));
    const im = new Image();
    im.onload = () => setImg(im);
    im.src = `${API_BASE}${underUrl}`;
  }, [underUrl]);

  // draw
  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx || !data || !now || !base || !view) return;
    ctx.clearRect(0, 0, W, H);
    const S = (p: Pt) => toScreen(view, p[0], p[1]);
    const path = (pts: Pt[], close = true) => {
      pts.forEach((p, i) => (i ? ctx.lineTo(...S(p)) : ctx.moveTo(...S(p))));
      if (close) ctx.closePath();
    };
    if (under && img && !hideImg) {
      const q = imageRect(under);
      const [x, y] = S([q.x0, q.y1]);
      ctx.globalAlpha = opacity;
      ctx.drawImage(img, x, y, (q.x1 - q.x0) * view.scale, (q.y1 - q.y0) * view.scale);
      ctx.globalAlpha = 1;
    }
    if (under && calib) {
      ctx.strokeStyle = "#d4006a";
      ctx.lineWidth = 2;
      for (const [px, py] of calib.pts) {
        const [cx, cy] = S(pxToPlan(under, px, py));
        ctx.beginPath();
        ctx.moveTo(cx - 8, cy);
        ctx.lineTo(cx + 8, cy);
        ctx.moveTo(cx, cy - 8);
        ctx.lineTo(cx, cy + 8);
        ctx.stroke();
      }
    }
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#c4c4c4";
    ctx.beginPath();
    for (const s of data.source.segments) {
      ctx.moveTo(...S([s.p[0], s.p[1]]));
      ctx.lineTo(...S([s.p[2], s.p[3]]));
    }
    ctx.stroke();
    ctx.fillStyle = "#555";
    ctx.font = "12px system-ui";
    for (const r of now.rooms) ctx.fillText(r.name, ...S(r.label_point));
    const changed = (w: { provenance: string; handles: string[] }) => w.handles.some((h) => allOps.some((o) => o.id === h));
    for (const w of now.walls) {
      ctx.fillStyle = changed(w) ? "rgba(140,90,210,0.55)" : "rgba(217,83,79,0.5)";
      ctx.strokeStyle = sel?.kind === "wall" && sel.id === w.id ? "#1a55c8" : "#a33";
      ctx.lineWidth = sel?.kind === "wall" && sel.id === w.id ? 3 : 1;
      ctx.beginPath();
      path(wallCorners(w));
      ctx.fill();
      ctx.stroke();
    }
    for (const o of now.openings) {
      ctx.strokeStyle = sel?.kind === "opening" && sel.id === o.id ? "#1a55c8" : changed(o) ? "#8c5ad2" : "#2e9e44";
      ctx.lineWidth = 5;
      ctx.beginPath();
      path([o.start, o.end], false);
      ctx.stroke();
    }
    const w = sel?.kind === "wall" ? now.walls.find((x) => x.id === sel.id) : undefined;
    if (w) {
      ctx.fillStyle = "#1a55c8";
      for (const p of [w.start, w.end]) ctx.fillRect(S(p)[0] - 4, S(p)[1] - 4, 8, 8);
    }
    if (tool === "wall" && anchor && hover) {
      ctx.strokeStyle = "#1a55c8";
      ctx.lineWidth = EDIT.defaultThicknessMm * view.scale;
      ctx.globalAlpha = 0.35;
      ctx.beginPath();
      path([anchor, orthogonal(anchor, hover)], false);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }, [data, now, base, view, sel, tool, anchor, hover, allOps, under, img, hideImg, opacity, calib]);

  const point = (e: RPointerEvent<HTMLCanvasElement>): { s: [number, number]; p: Pt } | null => {
    const c = canvas.current;
    if (!c || !view) return null;
    const r = c.getBoundingClientRect();
    const s: [number, number] = [((e.clientX - r.left) * W) / r.width, ((e.clientY - r.top) * H) / r.height];
    return { s, p: toPlan(view, s[0], s[1]) };
  };

  function onDown(e: RPointerEvent<HTMLCanvasElement>) {
    const q = point(e);
    if (!q || !committed || !view || busy) return;
    const { s, p } = q;
    if (under && calib) { // picking the two calibration points: nothing else happens meanwhile
      if (calib.pts.length < 2) setCalib({ ...calib, pts: [...calib.pts, planToPx(under, p[0], p[1])] });
      return;
    }
    if (needsScale) return setError("Set the scale of the underlay first (Set scale).");
    const tol = pxToMm(EDIT.hitPx, view.scale);
    const hit = hitTest(committed, p, tol);
    const hostOf = (h: Selection | null) => (h?.kind === "wall" ? committed.walls.find((w) => w.id === h.id) : h?.kind === "opening" ? committed.walls.find((w) => w.id === committed.openings.find((o) => o.id === h.id)?.wall_id) : undefined);
    const id = nextId(allOps);
    if (tool === "wall") {
      const at = snap(p, committed, view.scale);
      if (!anchor) return setAnchor(at);
      commit(addWallOp(id, anchor, orthogonal(anchor, at), Number(thickness) || EDIT.defaultThicknessMm));
      return setAnchor(null);
    }
    if (tool === "door" || tool === "window") {
      const host = hit?.kind === "wall" ? hostOf(hit) : undefined; // press on a bare wall; an opening there is edited with Select
      const dims = openingDims(tool, height, sill);
      if (!dims.ok) return setError(dims.error);
      setError(null);
      if (host) {
        e.currentTarget.setPointerCapture(e.pointerId);
        setDrag({ kind: "draw", host, open: tool, dims: dims.value, origin: p, cur: p });
      }
      return;
    }
    if (tool === "delete") {
      if (hit?.kind === "opening") commit(removeOpeningOp(id, committed.openings.find((o) => o.id === hit.id)!));
      else if (hit?.kind === "wall") commit(removeWallOp(id, committed.walls.find((w) => w.id === hit.id)!));
      return;
    }
    e.currentTarget.setPointerCapture(e.pointerId);
    const selected = sel?.kind === "wall" ? committed.walls.find((w) => w.id === sel.id) : undefined;
    const end = selected && endpointAt(selected, p, tol * 2);
    if (selected && end) return setDrag({ kind: end, wall: selected, origin: p, cur: p });
    setSel(hit);
    if (hit?.kind === "wall") setDrag({ kind: "move", wall: committed.walls.find((w) => w.id === hit.id)!, origin: p, cur: p });
    else if (hit?.kind === "opening") {
      const o = committed.openings.find((x) => x.id === hit.id)!;
      const host = hostOf(hit);
      if (host) setDrag({ kind: "slide", opening: o, host, origin: p, cur: p });
    } else if (!hit) setDrag({ kind: "pan", last: s });
  }

  function onMove(e: RPointerEvent<HTMLCanvasElement>) {
    const q = point(e);
    if (!q) return;
    setHover(q.p);
    if (!drag) return;
    if (drag.kind === "pan") {
      setView((v) => v && panBy(v, q.s[0] - drag.last[0], q.s[1] - drag.last[1]));
      setDrag({ kind: "pan", last: q.s });
    } else setDrag({ ...drag, cur: q.p });
  }

  function onUp() {
    if (drag && drag.kind !== "pan") commit(transient);
    setDrag(null);
  }

  async function saveCalibration() {
    if (!under || !calib || calib.pts.length < 2) return;
    const c = calibrationScale(calib.pts[0], calib.pts[1], Number(calib.distance));
    if (!c.ok) return setCalibError(c.error);
    setCalibError(null);
    setBusy(true);
    const r = await putCalibration(projectId, floor.id, calib.pts[0], calib.pts[1], Number(calib.distance));
    setBusy(false);
    if (!r.ok) return setCalibError(r.message);
    setCalib(null);
    setLocked(true);
    await load();
    onSaved();
  }

  async function save() {
    setBusy(true);
    setBlocked(null);
    setSaved(null);
    setError(null);
    const r = await saveEditsJob(projectId, floor.id, allOps, setJob);
    setBusy(false);
    setJob(null);
    if (r.ok) {
      setHist(EMPTY_HISTORY);
      setSel(null);
      setSaved(r.issues);
      await load();
      onSaved();
    } else if (r.kind === "blocked") setBlocked(r.issues);
    else setError(r.message);
  }

  const discardOk = () => hist.done.length === 0 || window.confirm(`Discard ${hist.done.length} unsaved change${hist.done.length === 1 ? "" : "s"}?`);
  if (error && !data) return <p role="alert">{error}</p>;
  if (!data) return <p role="status">Loading the plan…</p>;
  if (!base || !committed || !now) return <p role="alert">This floor was made before editing was supported: add it again from its DXF to edit it.</p>;
  return (
    <section aria-label={`Edit plan: ${floor.name}`}>
      <h3>Edit plan: {floor.name} <button type="button" onClick={() => discardOk() && onClose()} disabled={busy}>Close</button></h3>
      <p><small>Orthogonal walls, doors, windows (drawn by dragging along a wall) and room names. Rooms and everything built from them update when you save; the 3D viewer shows the saved version.</small></p>
      {under && (
        <UnderlayPanel underlay={under} opacity={opacity} setOpacity={setOpacity} hidden={hideImg} setHidden={setHideImg} locked={locked} setLocked={setLocked}
          calib={calib} setCalib={(c) => { setCalib(c); setCalibError(null); }} onSaveCalibration={saveCalibration} busy={busy} error={calibError} />
      )}
      <EditorToolbar tool={tool} setTool={(t) => { setTool(t); setAnchor(null); }}
        height={height} setHeight={setHeight} sill={sill} setSill={setSill} thickness={thickness} setThickness={setThickness}
        canUndo={hist.done.length > 0} canRedo={hist.undone.length > 0} onUndo={() => setHist(undo(hist))} onRedo={() => setHist(redo(hist))}
        pending={hist.done.length} busy={busy} onSave={save} onDiscard={() => { if (!discardOk()) return; setHist(EMPTY_HISTORY); setSel(null); setAnchor(null); }} />
      {busy && <p role="status">{job ? `${STAGE_LABEL[job.stage] ?? job.stage} (${job.progress}%)` : "Saving…"}</p>}
      {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
      {saved && (
        <div role="status">
          <p>Saved. Edits the drawing could not apply, and other notes about the result, are listed here:</p>
          <IssueList issues={saved.filter((i) => i.code.startsWith("edit_"))} />
          <details><summary>All issues of the saved floor ({saved.length})</summary><IssueList issues={saved} /></details>
        </div>
      )}
      {blocked && (
        <div role="alert">
          <p><strong>Nothing was saved:</strong> the edits give blocking issues. Change or undo them and save again.</p>
          <IssueList issues={blocked} />
        </div>
      )}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <canvas ref={canvas} width={W} height={H} aria-label="Editable plan" style={{ background: "#fff", maxWidth: "100%", border: "1px solid #ccc", touchAction: "none", cursor: tool === "select" ? "default" : "crosshair" }}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => setHover(null)} />
        <PlanInspector base={base} committed={committed} now={now} sel={sel} allOps={allOps} onOp={commit} disabled={busy} />
      </div>
    </section>
  );
}
