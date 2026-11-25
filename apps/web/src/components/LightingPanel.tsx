import { LightPlan } from "./LightPlan";
import { QUALITY, QUALITY_IDS, type QualityId } from "../lib/quality";
import { MAX_LIGHTS, type ArtificialLight, type SiteLighting } from "../lib/site-lighting";

type Props = {
  quality: QualityId;
  onQuality: (q: QualityId) => void;
  site: SiteLighting;
  onSite: (s: SiteLighting) => void;
  sunInfo: string | null; // where the sun is now at the saved location, e.g. "azimuth 120 deg, elevation 35 deg"
  canSave: boolean; // editor+ on a current version: the location, north and lights can be saved
  dirty: boolean;
  onSave: () => void;
  projectId: string | null; // the light plan needs a saved project
  planFloors: { id: string; name: string }[];
  share: string | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  floorName: (id: string) => string;
};

const field = { width: 70 } as const;

/** Lighting controls. Quality is for everyone (viewer-local); location, north and artificial lights are
 *  project settings, editable and saveable by editors only. The sun follows the current local date and time. */
export function LightingPanel(p: Props) {
  const loc = p.site.location;
  const edit = p.canSave;
  const setLoc = (latitude: number, longitude: number) => p.onSite({ ...p.site, location: { latitude, longitude } });
  const light = p.site.lights.find((l) => l.id === p.selectedId) ?? null;
  const patch = (l: Partial<ArtificialLight>) => p.onSite({ ...p.site, lights: p.site.lights.map((x) => (x.id === p.selectedId ? { ...x, ...l } : x)) });
  const num = (v: string, fallback: number) => (v.trim() === "" || Number.isNaN(Number(v)) ? fallback : Number(v));
  return (
    <details open aria-label="Lighting" style={{ marginTop: 8 }}>
      <summary>Lighting</summary>
      <label>
        Quality{" "}
        <select value={p.quality} onChange={(e) => p.onQuality(e.target.value as QualityId)}>
          {QUALITY_IDS.map((q) => (
            <option key={q} value={q}>
              {QUALITY[q].label}
            </option>
          ))}
        </select>
      </label>
      {p.quality === "accuracy" && <div>Accuracy: flat look, no textures, shadows, reflections or added lights.</div>}
      <fieldset style={{ marginTop: 6 }}>
        <legend>Site (saved with the project)</legend>
        <label>
          Latitude{" "}
          <input aria-label="Latitude" type="number" step="0.1" min={-90} max={90} style={field} disabled={!edit} value={loc?.latitude ?? ""} onChange={(e) => setLoc(Math.max(-90, Math.min(90, num(e.target.value, 0))), loc?.longitude ?? 0)} />
        </label>{" "}
        <label>
          Longitude{" "}
          <input aria-label="Longitude" type="number" step="0.1" min={-180} max={180} style={field} disabled={!edit} value={loc?.longitude ?? ""} onChange={(e) => setLoc(loc?.latitude ?? 0, Math.max(-180, Math.min(180, num(e.target.value, 0))))} />
        </label>
        <label>
          Building north (deg clockwise from plan up){" "}
          <input aria-label="North angle" type="number" step="1" min={0} max={359} style={field} disabled={!edit} value={p.site.north_deg} onChange={(e) => p.onSite({ ...p.site, north_deg: ((num(e.target.value, 0) % 360) + 360) % 360 })} />
        </label>
        {loc && edit && <button onClick={() => p.onSite({ ...p.site, location: null })}>Clear location</button>}
        {!loc && <div>No location: default lighting.</div>}
      </fieldset>
      {p.sunInfo && <div>{p.sunInfo}</div>}
      <fieldset style={{ marginTop: 6 }}>
        <legend>
          Lights ({p.site.lights.length}/{MAX_LIGHTS})
        </legend>
        <LightPlan projectId={p.projectId} floors={p.planFloors} share={p.share} lights={p.site.lights} selectedId={p.selectedId} onSelect={p.onSelect} onChange={(lights) => p.onSite({ ...p.site, lights })} canEdit={edit} />
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {p.site.lights.map((l) => (
            <li key={l.id}>
              <button aria-pressed={l.id === p.selectedId} onClick={() => p.onSelect(l.id === p.selectedId ? null : l.id)}>
                {l.kind} {l.id} ({p.floorName(l.floor_id)})
              </button>
            </li>
          ))}
        </ul>
        {light && (
          <div>
            <label>
              Type{" "}
              <select value={light.kind} disabled={!edit} onChange={(e) => patch({ kind: e.target.value as ArtificialLight["kind"] })}>
                <option value="point">point</option>
                <option value="spot">spot (down)</option>
              </select>
            </label>{" "}
            <label>
              Colour <input aria-label="Light colour" type="color" disabled={!edit} value={light.color} onChange={(e) => patch({ color: e.target.value })} />
            </label>
            <div>
              <label>
                Intensity {light.intensity.toFixed(1)}{" "}
                <input aria-label="Light intensity" type="range" min={0} max={10} step={0.1} disabled={!edit} value={light.intensity} onChange={(e) => patch({ intensity: Number(e.target.value) })} />
              </label>
            </div>
            <div>
              <label>
                Plan x (mm){" "}
                <input aria-label="Light x" type="number" step={50} style={{ width: 80 }} disabled={!edit} value={light.x_mm} onChange={(e) => patch({ x_mm: Math.round(num(e.target.value, light.x_mm)) })} />
              </label>{" "}
              <label>
                y (mm){" "}
                <input aria-label="Light y" type="number" step={50} style={{ width: 80 }} disabled={!edit} value={light.y_mm} onChange={(e) => patch({ y_mm: Math.round(num(e.target.value, light.y_mm)) })} />
              </label>
            </div>
            <label>
              Height above floor (mm){" "}
              <input aria-label="Light height" type="number" min={0} max={100000} step={50} style={{ width: 80 }} disabled={!edit} value={light.height_mm} onChange={(e) => patch({ height_mm: Math.max(0, num(e.target.value, 0)) })} />
            </label>
            {edit && (
              <button
                onClick={() => {
                  p.onSite({ ...p.site, lights: p.site.lights.filter((x) => x.id !== light.id) });
                  p.onSelect(null);
                }}
              >
                Remove light
              </button>
            )}
          </div>
        )}
      </fieldset>
      {edit && (
        <button disabled={!p.dirty} onClick={p.onSave}>
          {p.dirty ? "Save location, north and lights" : "Saved"}
        </button>
      )}
      {!edit && <div>Location, north and lights are saved by editors; you can still change quality, date and time.</div>}
    </details>
  );
}
