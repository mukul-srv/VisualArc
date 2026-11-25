import { labelOf, libraryFor } from "../lib/materials";

/** Material choice for the selected element. Viewers (and share links, old versions) see it but cannot change it. */
export function MaterialPicker({ type, value, disabled, onChange }: { type: string; value: string | null; disabled: boolean; onChange: (id: string | null) => void }) {
  const options = libraryFor(type);
  if (disabled) return <div aria-label="Material">Material: {value ? labelOf(value) : "default"}</div>;
  if (options.length === 0 && !value) return null;
  return (
    <label style={{ display: "block", marginTop: 6 }}>
      Material{" "}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">default</option>
        {options.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
        {value && !options.some((m) => m.id === value) && <option value={value}>{labelOf(value)}</option>}
      </select>
    </label>
  );
}
