"use client";

import { type ConventionsSpec, type LayerRole, type PresetInfo } from "../lib/conventions";

const ROLE_LABEL: Record<string, string> = {
  wall: "wall",
  wall_exterior: "exterior wall",
  wall_interior: "interior wall",
  floor: "floor boundary",
  door: "door",
  window: "window",
  column: "column (rectangle or circle)",
  balcony: "balcony / terrace outline",
  ignore: "ignore (reported, not read)",
};

// Preset choice plus a role selector for every layer the preset does not know. A layer left on
// "unmapped" is still reported as an issue by the engine; "ignore" is also reported.
export function ConventionsPanel(p: {
  spec: ConventionsSpec;
  setSpec: (s: ConventionsSpec) => void;
  presets: PresetInfo[];
  roles: string[];
  layers: LayerRole[]; // from the upload inventory; empty on the project page
  disabled?: boolean;
  readOnly?: boolean;
}) {
  const { spec, setSpec, presets, roles, layers, disabled, readOnly } = p;
  const preset = presets.find((x) => x.id === spec.preset);
  const known = new Set(Object.keys(preset?.layers ?? {}));
  // listed: the drawing's layers the preset does not know (mapped or not), plus saved mapping entries
  // (the server's role, not a name match, decides what the preset knows: floor prefixes are stripped)
  const names = [...new Set([...layers.filter((l) => l.role === null || l.layer in spec.mapping).map((l) => l.layer), ...Object.keys(spec.mapping)])]
    .filter((n) => !known.has(n.toUpperCase()))
    .sort();
  const count = (n: string) => layers.find((l) => l.layer === n)?.entities;
  const setRole = (layer: string, role: string) => {
    const mapping = { ...spec.mapping };
    if (role === "") delete mapping[layer];
    else mapping[layer] = role;
    setSpec({ ...spec, mapping });
  };
  return (
    <section aria-label="Layer conventions">
      <h3>Layer conventions</h3>
      <label>
        Preset{" "}
        <select value={spec.preset} disabled={disabled || readOnly} onChange={(e) => setSpec({ ...spec, preset: e.target.value })}>
          {presets.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
      </label>
      {preset && <p><small>{preset.source}</small></p>}
      {names.length === 0 ? (
        <p>Every layer in this drawing is mapped by the preset.</p>
      ) : (
        <>
          <p>Layers the preset does not know. Unmapped layers are not read and are reported as issues.</p>
          <ul>
            {names.map((n) => (
              <li key={n}>
                {n}{count(n) !== undefined ? ` (${count(n)} entities)` : ""}{" "}
                <select aria-label={`Role for layer ${n}`} value={spec.mapping[n] ?? ""} disabled={disabled || readOnly} onChange={(e) => setRole(n, e.target.value)}>
                  <option value="">unmapped</option>
                  {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
                </select>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
