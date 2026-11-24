import { PROVENANCE_LABEL, type Panel } from "../lib/selection";

// Provenance is always spelled out in text; assumed/inferred values are also emphasised.
const EMPHASIS = { source_extracted: "#9fd29f", user_provided: "#9fc3ff", defaulted: "#ffcc66", inferred: "#ff9fd0", user_modified: "#c9a0ff" };

export function MetadataPanel({ panel }: { panel: Panel | null }) {
  if (!panel) return <aside aria-label="Selection">Click a wall, junction, floor or opening.</aside>;
  return (
    <aside aria-label="Selection">
      <h2 style={{ margin: "0 0 4px", fontSize: 16 }}>
        {panel.title} <code>{panel.id}</code>
      </h2>
      <table>
        <tbody>
          {panel.rows.map((r) => (
            <tr key={r.label}>
              <th style={{ textAlign: "left", paddingRight: 8, fontWeight: 400 }}>{r.label}</th>
              <td>
                {r.value}
                {r.provenance && (
                  <span style={{ marginLeft: 6, color: EMPHASIS[r.provenance] }}>[{PROVENANCE_LABEL[r.provenance]}]</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details style={{ marginTop: 6 }}>
        <summary>{panel.sourcesLabel} ({panel.sources.length})</summary>
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {panel.sources.length ? (
            panel.sources.map((s) => <li key={s}>{s}</li>)
          ) : (
            <li>none (derived by the engine)</li>
          )}
        </ul>
      </details>
    </aside>
  );
}
