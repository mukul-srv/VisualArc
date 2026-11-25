import { useEffect, useRef } from "react";
import type { TraceStatus } from "../lib/pathtrace";
import { RESOLUTION_IDS, RESOLUTIONS, SAMPLE_LIMITS, TIME_LIMITS, TRACE_NOTES, clampTrace, type ResolutionId, type TraceSettings } from "../lib/render-settings";

export type RenderState = {
  phase: "idle" | "building" | "running" | "done" | "error";
  status: TraceStatus | null;
  message: string | null; // error, or a note such as "the resolution was reduced to fit the GPU"
  size: { w: number; h: number } | null;
  result: { url: string; name: string; kind: "render" | "screenshot" } | null;
  canvas: HTMLCanvasElement | null; // the live path-traced canvas while running
};
export const IDLE_RENDER: RenderState = { phase: "idle", status: null, message: null, size: null, result: null, canvas: null };

type Props = {
  state: RenderState;
  settings: TraceSettings;
  onSettings: (s: TraceSettings) => void;
  onStart: () => void;
  onStop: () => void;
  onScreenshot: () => void;
  onClose: () => void;
};

/** Dialog for the path-traced still and the realtime screenshot. Everyone who can see the model can use it
 *  (it reads the scene and writes only a PNG on the user's machine). */
export function RenderPanel({ state, settings, onSettings, onStart, onStop, onScreenshot, onClose }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const busy = state.phase === "building" || state.phase === "running";
  useEffect(() => {
    const el = host.current;
    const canvas = state.canvas;
    if (!el || !canvas) return;
    el.appendChild(canvas);
    return () => {
      canvas.remove();
    };
  }, [state.canvas]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const set = (p: Partial<TraceSettings>) => onSettings(clampTrace({ ...settings, ...p }));
  const st = state.status;
  return (
    <div role="dialog" aria-modal="true" aria-label="Render" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10 }}>
      <div style={{ background: "#1c1c20", color: "#eee", font: "13px monospace", padding: 14, maxWidth: "min(900px, 95vw)", maxHeight: "95vh", overflow: "auto" }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 16 }}>Render current view</h2>
        <div>
          <label>
            Resolution{" "}
            <select aria-label="Resolution" disabled={busy} value={settings.resolution} onChange={(e) => set({ resolution: e.target.value as ResolutionId })}>
              {RESOLUTION_IDS.map((r) => (
                <option key={r} value={r}>
                  {RESOLUTIONS[r].label}
                </option>
              ))}
            </select>
          </label>{" "}
          <button disabled={busy} onClick={onScreenshot}>
            Screenshot (realtime PNG)
          </button>
        </div>
        <fieldset disabled={busy} style={{ marginTop: 6 }}>
          <legend>Path-traced still</legend>
          <label>
            Samples {settings.samples}{" "}
            <input aria-label="Target samples" type="range" min={SAMPLE_LIMITS.min} max={SAMPLE_LIMITS.max} step={1} value={settings.samples} onChange={(e) => set({ samples: Number(e.target.value) })} />
          </label>
          <div>
            <label>
              Time limit (s, 0 = none){" "}
              <input aria-label="Time limit" type="number" min={0} max={TIME_LIMITS.max} step={5} style={{ width: 70 }} value={settings.timeLimitSec} onChange={(e) => set({ timeLimitSec: Number(e.target.value) })} />
            </label>{" "}
            stops at whichever comes first
          </div>
          <button onClick={onStart}>Start render</button>
        </fieldset>
        {busy && (
          <div style={{ marginTop: 6 }}>
            <button onClick={onStop}>Stop</button>{" "}
            {state.phase === "building" || !st ? (
              "Building the scene for the path tracer…"
            ) : st.compiling && st.samples === 0 ? (
              "Compiling shaders…"
            ) : (
              <>
                <progress aria-label="Render progress" max={1} value={st.progress} /> {st.samples} / {settings.samples} samples, {(st.elapsedMs / 1000).toFixed(1)} s
              </>
            )}
          </div>
        )}
        {state.size && <div>Output {state.size.w} x {state.size.h} px</div>}
        {state.message && <div role="alert" style={{ color: state.phase === "error" ? "#ff8080" : "#ffcc66" }}>{state.message}</div>}
        <div ref={host} style={{ marginTop: 6 }} />
        {state.result && (
          <div style={{ marginTop: 6 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={state.result.url} alt={state.result.kind === "render" ? "Path-traced still" : "Screenshot"} style={{ maxWidth: "100%", maxHeight: "50vh", display: "block" }} />
            <a href={state.result.url} download={state.result.name}>
              Download PNG ({state.result.name})
            </a>
          </div>
        )}
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
          {TRACE_NOTES.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
        <button style={{ marginTop: 8 }} onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
