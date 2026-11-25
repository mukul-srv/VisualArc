"use client";

import { MIN_CALIBRATION_PX, mmPerPx, type Underlay } from "../lib/underlay";

export type Calibrating = { pts: [number, number][]; distance: string };

type Props = {
  underlay: Underlay;
  opacity: number;
  setOpacity: (n: number) => void;
  hidden: boolean;
  setHidden: (b: boolean) => void;
  locked: boolean;
  setLocked: (b: boolean) => void;
  calib: Calibrating | null;
  setCalib: (c: Calibrating | null) => void;
  onSaveCalibration: () => void;
  busy: boolean;
  error: string | null;
};

/** Underlay controls: look (opacity, hide), the scale lock and the two-point calibration. The picture is only
 *  a guide: nothing is detected from it, everything on the floor is traced by hand with the tools. */
export function UnderlayPanel(p: Props) {
  const { underlay: u, calib } = p;
  const done = u.calibration !== null;
  return (
    <fieldset aria-label="Underlay" style={{ margin: "8px 0" }}>
      <legend>Underlay (trace over this picture)</legend>
      <label>Opacity <input type="range" min={0.1} max={1} step={0.05} value={p.opacity} onChange={(e) => p.setOpacity(Number(e.target.value))} aria-label="Underlay opacity" /></label>{" "}
      <label><input type="checkbox" checked={p.hidden} onChange={(e) => p.setHidden(e.target.checked)} /> Hide</label>{" "}
      <label><input type="checkbox" checked={p.locked} disabled={!done} onChange={(e) => p.setLocked(e.target.checked)} /> Lock scale</label>
      {done ? (
        <p>
          Scale: 1 px = {Number(mmPerPx(u).toPrecision(4))} mm (you entered {u.calibration!.distance_mm} mm between two points).{" "}
          <button type="button" disabled={p.locked || p.busy || calib !== null} onClick={() => p.setCalib({ pts: [], distance: "" })}>Recalibrate</button>
          {p.locked && <small> Unlock to change the scale. Walls already traced keep their size.</small>}
        </p>
      ) : (
        <p role="status">
          <strong>Set the scale first.</strong> Click two points on the picture whose real distance you know, then enter that distance.{" "}
          {calib === null && <button type="button" disabled={p.busy} onClick={() => p.setCalib({ pts: [], distance: "" })}>Set scale</button>}
        </p>
      )}
      {calib && (
        <div>
          <p>Points picked: {calib.pts.length} of 2 (at least {MIN_CALIBRATION_PX} px apart){calib.pts.map(([x, y], i) => ` P${i + 1} (${Math.round(x)}, ${Math.round(y)})`).join("")}</p>
          <label>Real distance between the points (mm) <input aria-label="Real distance in mm" inputMode="decimal" size={9} value={calib.distance} onChange={(e) => p.setCalib({ ...calib, distance: e.target.value })} /></label>{" "}
          <button type="button" disabled={calib.pts.length < 2 || p.busy} onClick={p.onSaveCalibration}>Save scale</button>{" "}
          <button type="button" disabled={calib.pts.length === 0 || p.busy} onClick={() => p.setCalib({ ...calib, pts: [] })}>Clear points</button>{" "}
          <button type="button" disabled={p.busy} onClick={() => p.setCalib(null)}>Cancel</button>
        </div>
      )}
      {p.error && <p role="alert" style={{ color: "#b00020" }}>{p.error}</p>}
    </fieldset>
  );
}
