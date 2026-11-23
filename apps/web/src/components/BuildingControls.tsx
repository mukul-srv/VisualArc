import type { Building, BuildingFloor } from "../lib/building";
import { buildingStats, floorStats, GAP, type View, type ViewMode } from "../lib/building-view";

const MODES: { id: ViewMode; label: string }[] = [
  { id: "whole", label: "Whole building" },
  { id: "isolate", label: "Isolate floor" },
  { id: "exploded", label: "Exploded" },
];

/** View mode of a multi-floor project: the whole building, one floor (the others hidden or ghosted),
 *  or the floors lifted apart. The floor switcher below picks the active floor. */
export function BuildingControls({ view, disabled, onChange }: { view: View; disabled: boolean; onChange: (v: View, reframe: boolean) => void }) {
  return (
    <div role="group" aria-label="Building view" style={{ marginTop: 6 }}>
      {MODES.map((m) => (
        <button key={m.id} disabled={disabled} aria-pressed={view.mode === m.id} onClick={() => view.mode !== m.id && onChange({ ...view, mode: m.id }, true)}>
          {m.label}
        </button>
      ))}
      {view.mode === "isolate" && (
        <label style={{ display: "block" }}>
          <input type="checkbox" checked={view.ghost} disabled={disabled} onChange={(e) => onChange({ ...view, ghost: e.target.checked }, false)} /> Show other floors faintly
        </label>
      )}
      {view.mode === "exploded" && (
        <label style={{ display: "block" }}>
          Gap {view.gap} m{" "}
          <input type="range" aria-label="Floor gap" min={GAP.min} max={GAP.max} step={GAP.step} value={view.gap} disabled={disabled}
            onChange={(e) => onChange({ ...view, gap: Number(e.target.value) }, false)} />
        </label>
      )}
    </div>
  );
}

/** Building-wide and active-floor numbers from the building API (engine values, not computed here). */
export function BuildingStats({ building, active }: { building: Building; active?: BuildingFloor }) {
  const b = buildingStats(building);
  const f = active && floorStats(active);
  if (building.version === 0) return null; // a past version: no building data
  return (
    <div style={{ marginBottom: 8 }}>
      <div><b>Building</b>: {b.floors} floors, {b.rooms} rooms, {b.area}, height {b.height}</div>
      {active && f && <div><b>{active.name}</b>: {f.rooms} rooms, {f.area}, height {f.height}</div>}
    </div>
  );
}
