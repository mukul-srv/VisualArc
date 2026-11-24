"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fit, getPlanOverlay, LEGEND, overlayBounds, toScreen, wallCorners, type OverlayData } from "../lib/overlay";
import type { Floor } from "../lib/project";
import styles from "./dashboard.module.css";

const W = 720;
const H = 520;
type Layers = Record<"source" | "walls" | "openings" | "boundary", boolean>;

// Read-only: the source drawing's lines (grey) under the built walls, openings and floor boundary (coloured).
export function PlanOverlay({ projectId = "", floors = [], share, overlay }: { projectId?: string; floors?: Floor[]; share?: string | null; overlay?: Omit<OverlayData, "floor_id"> }) {
  const [floorId, setFloorId] = useState(floors[0]?.id ?? "");
  const [fetched, setData] = useState<OverlayData | null>(null);
  const data = useMemo(() => (overlay ? { floor_id: "", ...overlay } : fetched) as OverlayData | null, [overlay, fetched]); // `overlay`: drawn from data, no fetch
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<Layers>({ source: true, walls: true, openings: true, boundary: true });
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!floorId || overlay) return;
    let live = true;
    getPlanOverlay(projectId, floorId, fetch, share).then((r) => {
      if (!live) return;
      if (r.ok) {
        setData(r.overlay);
        setError(null);
      } else {
        setData(null);
        setError(r.message);
      }
    });
    return () => {
      live = false;
    };
  }, [projectId, floorId, share, overlay]);

  useEffect(() => {
    const c = canvas.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    ctx.clearRect(0, 0, W, H);
    const b = data && overlayBounds(data);
    if (!data || !b) return;
    const f = fit(b, W, H);
    const poly = (pts: [number, number][], close = true) => {
      pts.forEach((p, i) => (i ? ctx.lineTo(...toScreen(f, p[0], p[1])) : ctx.moveTo(...toScreen(f, p[0], p[1]))));
      if (close) ctx.closePath();
    };
    if (show.source)
      for (const wall of [false, true]) {
        ctx.strokeStyle = LEGEND[wall ? 1 : 0].color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (const s of data.source.segments.filter((x) => x.wall === wall)) {
          ctx.moveTo(...toScreen(f, s.p[0], s.p[1]));
          ctx.lineTo(...toScreen(f, s.p[2], s.p[3]));
        }
        ctx.stroke();
      }
    if (show.boundary)
      for (const bd of data.model.boundaries) {
        ctx.strokeStyle = LEGEND[4].color;
        ctx.setLineDash(bd.inferred ? [6, 4] : []);
        ctx.lineWidth = 2;
        ctx.beginPath();
        poly(bd.polygon);
        ctx.stroke();
      }
    ctx.setLineDash([]);
    if (show.walls) {
      ctx.fillStyle = "rgba(217,83,79,0.55)";
      ctx.strokeStyle = LEGEND[2].color;
      for (const w of data.model.walls) {
        ctx.beginPath();
        poly(wallCorners(w));
        ctx.fill();
        ctx.stroke();
      }
      ctx.fillStyle = "rgba(217,83,79,0.35)";
      for (const j of data.model.junctions) {
        ctx.beginPath();
        poly(j);
        ctx.fill();
      }
    }
    if (show.openings)
      for (const o of data.model.openings) {
        ctx.strokeStyle = LEGEND[3].color;
        ctx.lineWidth = 4;
        ctx.setLineDash(o.inferred ? [6, 4] : []);
        ctx.beginPath();
        poly([o.start, o.end], false);
        ctx.stroke();
      }
    ctx.setLineDash([]);
  }, [data, show]);

  if (!overlay && !floors.length) return <p>No floors.</p>;
  return (
    <div>
      <div className={styles.row}>
        {!overlay && <label>
          Floor{" "}
          <select value={floorId} onChange={(e) => setFloorId(e.target.value)}>
            {floors.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </label>}
        {(["source", "walls", "openings", "boundary"] as const).map((k) => (
          <label key={k}>
            <input type="checkbox" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} /> {k}
          </label>
        ))}
      </div>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {data?.source.truncated && (
        <p role="status">Only {data.source.segments.length} of {data.source.total} source lines are drawn (wall layers first).</p>
      )}
      <canvas ref={canvas} width={W} height={H} aria-label="Plan of the drawing with the built model over it" style={{ background: "#fff", maxWidth: "100%", border: "1px solid #ccc" }} />
      <ul aria-label="Legend" style={{ listStyle: "none", padding: 0, display: "flex", gap: 12, flexWrap: "wrap" }}>
        {LEGEND.map((l) => (
          <li key={l.key}>
            <span style={{ display: "inline-block", width: 12, height: 12, background: l.color, marginRight: 4 }} />
            {l.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
