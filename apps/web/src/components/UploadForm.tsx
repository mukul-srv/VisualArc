import { isGenerationId, type Preflight, type Presets } from "../lib/api";
import { BUILDING_TYPES, UNITS, unitsDoubtful, type FormValues } from "../lib/params";
import { bboxSize, type SplitRow } from "../lib/split";
import { HELP } from "../lib/help";
import { Hint } from "./Hint";

export type ProjectTarget = { on: boolean; target: string; floorName: string; elevation: string };

type Props = {
  pre: Preflight;
  form: FormValues;
  setForm: (f: FormValues) => void;
  presets: Presets | null; // from the backend; null = not loaded, so no placeholder numbers
  rows: SplitRow[];
  setRow: (i: number, patch: Partial<SplitRow>) => void;
  projectName: string;
  setProjectName: (s: string) => void;
  proj: ProjectTarget;
  setProj: (p: ProjectTarget) => void;
  errors: string[];
  reviewed?: boolean; // a review exists: "Re-run review" below replaces this button
  addingTo?: boolean; // /new?project=: the target is fixed, so the floor fields come first and the id is not shown
  disabled: boolean;
  onSubmit: () => void;
};

const block = { display: "block", margin: "6px 0" } as const;

/** Essentials always visible; every expert control sits under a collapsed "Advanced settings".
 *  Empty advanced fields are omitted from the request and filled (and tagged) by the backend. */
export function UploadForm(p: Props) {
  const { pre, form, setForm, presets, rows, setRow } = p;
  const splitting = (pre.floor_candidates?.length ?? 0) >= 2;
  const preset = presets?.[form.buildingType];
  const step = preset?.floor_to_floor;
  const field = (k: keyof Omit<FormValues, "buildingType" | "units">, label: string, key: keyof NonNullable<typeof preset>) => (
    <label style={block}>
      {label}{" "}
      <input
        id={`f-${k}`}
        value={form[k]}
        inputMode="decimal"
        placeholder={preset ? `default ${preset[key]}` : undefined}
        onChange={(e) => setForm({ ...form, [k]: e.target.value })}
      />
    </label>
  );
  const nameError = p.errors.find((e) => e.startsWith("Floor name is required"));
  const listErrors = p.errors.filter((e) => e !== nameError);
  const floorFields = (
    <>
      <label style={block}>
        Floor name{" "}
        <input value={p.proj.floorName} aria-invalid={nameError ? true : undefined} aria-describedby={nameError ? "floor-name-error" : undefined} onChange={(e) => p.setProj({ ...p.proj, floorName: e.target.value })} />
        {nameError && <span id="floor-name-error" role="alert"> {nameError}</span>}
      </label>
      <label style={block}>
        Floor elevation (mm){" "}
        <input inputMode="decimal" value={p.proj.elevation} placeholder={step === undefined ? undefined : isGenerationId(p.proj.target.trim()) ? `default highest floor + ${step}` : "default 0"} onChange={(e) => p.setProj({ ...p.proj, elevation: e.target.value })} /> unique per project
      </label>
    </>
  );
  const kept = rows.filter((r) => !r.exclude);

  return (
    <>
      <fieldset style={{ border: "none", padding: 0, margin: "8px 0" }}>
        <legend>Building type<Hint text={HELP.buildingType} /></legend>
        {BUILDING_TYPES.map((t) => (
          <label key={t} style={{ marginRight: 16, textTransform: "capitalize" }}>
            <input type="radio" name="building-type" value={t} checked={form.buildingType === t} onChange={() => setForm({ ...form, buildingType: t })} /> {t}
          </label>
        ))}
      </fieldset>
      {(pre.needs.includes("units") || unitsDoubtful(pre)) && (
        <label style={block}>
          {pre.needs.includes("units")
            ? "What unit was this drawing made in?"
            : "The drawing's size looks wrong for the units in its header. If you know the real unit, choose it (it replaces the header):"}{" "}
          <select id="f-units" value={form.units} onChange={(e) => setForm({ ...form, units: e.target.value })}>
            <option value="">{pre.needs.includes("units") ? "select (required)" : "keep the header's units"}</option>
            {UNITS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </select>
        </label>
      )}
      {splitting && (
        <>
          <h2>Floors found in this drawing</h2>
          <p>Choose the floors to build and name them. Excluded floors are reported as not reconstructed.</p>
          <label style={block}>
            Project name <input value={p.projectName} onChange={(e) => p.setProjectName(e.target.value)} />
          </label>
          <table>
            <thead>
              <tr>
                <th>Key</th><th>Size (mm)</th><th>Build</th><th>Name</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const s = bboxSize(pre.floor_candidates![i]);
                return (
                  <tr key={r.key}>
                    <td>{r.key}</td>
                    <td>{s.width.toFixed(0)} x {s.height.toFixed(0)}</td>
                    <td><input type="checkbox" aria-label={`Build ${r.key}`} checked={!r.exclude} onChange={(e) => setRow(i, { exclude: !e.target.checked })} /></td>
                    <td><input aria-label={`Name ${r.key}`} value={r.name} disabled={r.exclude} onChange={(e) => setRow(i, { name: e.target.value })} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
      {p.addingTo && !splitting && floorFields}
      <details style={{ margin: "12px 0" }}>
        <summary title={HELP.advancedUpload}>Advanced settings</summary>
        <p>Leave a field empty to use the default shown; defaults are reported as assumed in the result.</p>
        {field("wallHeight", "Wall height (mm)", "wall_height")}
        {field("ceilingHeight", "Ceiling height (mm)", "ceiling_height")}
        {field("doorHeight", "Door height (mm)", "door_height")}
        {field("windowHeight", "Window height (mm)", "window_height")}
        {field("windowSill", "Window sill (mm)", "window_sill")}
        {splitting && (
          <>
            <h3>Per-floor placement</h3>
            <p>Offsets (mm) start from the floor&apos;s lower-left corner and are <em>proposed</em> until you confirm them.</p>
            <table>
              <thead>
                <tr>
                  <th>Key</th><th>Elevation (mm)</th><th>Offset X (mm)</th><th>Offset Y (mm)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.key}>
                    <td>{r.key}</td>
                    <td><input aria-label={`Elevation ${r.key}`} inputMode="decimal" value={r.elevation} disabled={r.exclude} placeholder={r.exclude || step === undefined ? undefined : `default ${kept.indexOf(r) * step}`} onChange={(e) => setRow(i, { elevation: e.target.value })} /></td>
                    <td><input aria-label={`Offset X ${r.key}`} inputMode="decimal" value={r.offsetX} disabled={r.exclude} onChange={(e) => setRow(i, { offsetX: e.target.value })} /> proposed</td>
                    <td><input aria-label={`Offset Y ${r.key}`} inputMode="decimal" value={r.offsetY} disabled={r.exclude} onChange={(e) => setRow(i, { offsetY: e.target.value })} /> proposed</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {!splitting && !p.addingTo && (
          <>
            <label style={block}>
              <input type="checkbox" checked={p.proj.on} onChange={(e) => p.setProj({ ...p.proj, on: e.target.checked })} /> Add to a project (multi-floor){" "}
              <small>Needed to share, keep versions or edit floors later; without it the model stays standalone.</small>
            </label>
            {p.proj.on && (
              <>
                <label style={block}>
                  Project id (existing) or name (new){" "}
                  <input value={p.proj.target} onChange={(e) => p.setProj({ ...p.proj, target: e.target.value })} />
                </label>
                {floorFields}
              </>
            )}
          </>
        )}
      </details>
      {listErrors.length > 0 && (
        <ul role="alert" style={{ color: "#b00020" }}>
          {listErrors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {!p.reviewed && (
        <button disabled={p.disabled} onClick={p.onSubmit}>
          Review
        </button>
      )}
    </>
  );
}
