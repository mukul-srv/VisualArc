import { HELP } from "../lib/help";

type Props = {
  walking: boolean;
  top: boolean;
  measuring: boolean;
  roofPresent: boolean;
  roofOn: boolean;
  fullscreen: boolean;
  onWalk: () => void;
  onRoof: () => void;
  onReset: () => void;
  onFullscreen: () => void;
  onTop: () => void;
  onMeasure: () => void;
};

/** The viewer's essentials are always visible: walk, roof (when the model has one), reset view and
 *  full screen. The less common tools (top-down plan, measuring) sit under More. */
export function ViewerToolbar(p: Props) {
  return (
    <div role="toolbar" aria-label="Viewer tools" style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      <button onClick={p.onWalk} aria-pressed={p.walking} title={HELP.walk}>{p.walking ? "Exit walk (Esc)" : "Walk"}</button>
      {p.roofPresent && (
        <button onClick={p.onRoof} aria-pressed={p.roofOn} title={HELP.roof}>{p.roofOn ? "Roof: on" : "Roof: off"}</button>
      )}
      <button disabled={p.walking} onClick={p.onReset} title={HELP.reset}>Reset view</button>
      <button onClick={p.onFullscreen} aria-pressed={p.fullscreen} title={HELP.fullscreen}>{p.fullscreen ? "Exit full screen" : "Full screen"}</button>
      <details>
        <summary title={HELP.more} style={{ cursor: "pointer" }}>More</summary>
        <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
          <button disabled={p.walking} onClick={p.onTop} title={HELP.topdown}>{p.top ? "Perspective" : "Top-down"}</button>
          <button disabled={p.walking} onClick={p.onMeasure} title={HELP.measure}>{p.measuring ? "Measure: on (Esc)" : "Measure"}</button>
        </div>
      </details>
    </div>
  );
}
