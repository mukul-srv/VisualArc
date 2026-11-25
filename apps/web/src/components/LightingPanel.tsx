import { LightPlan } from "./LightPlan";
import { QUALITY, QUALITY_IDS, type QualityId } from "../lib/quality";
import { mapClickToLatLon, MAX_LIGHTS, type ArtificialLight, type SiteLighting } from "../lib/site-lighting";

export type SunSettings = { date: string; hours: number; utcOffset: number; intensity: number };
type Props = {
  quality: QualityId;
  onQuality: (q: QualityId) => void;
  site: SiteLighting;
  onSite: (s: SiteLighting) => void;
  sun: SunSettings;
  onSun: (s: SunSettings) => void;
  sunInfo: string | null; // e.g. "azimuth 120 deg, elevation 35 deg"
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

const hhmm = (h: number) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60) % 60).padStart(2, "0")}`;
const field = { width: 70 } as const;

/** Lighting controls. Quality, date, time and sun intensity are for everyone (viewer-local); location, north
 *  and artificial lights are project settings, editable and saveable by editors only. */
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
        <div
          role="img"
          aria-label="World map: click to set the location (keyboard users: type the latitude and longitude instead)"
          onClick={(e) => {
            if (!edit) return;
            const r = e.currentTarget.getBoundingClientRect();
            const c = mapClickToLatLon((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
            setLoc(c.latitude, c.longitude);
          }}
          style={{ position: "relative", width: 260, height: 130, marginTop: 4, cursor: edit ? "crosshair" : "default", backgroundImage: "url(/world.svg)", backgroundSize: "100% 100%" }}
        >
          {loc && <span style={{ position: "absolute", left: `${((loc.longitude + 180) / 360) * 100}%`, top: `${((90 - loc.latitude) / 180) * 100}%`, width: 8, height: 8, margin: -4, borderRadius: 4, background: "#ff3366" }} />}
        </div>
        <label>
          Building north (deg clockwise from plan up){" "}
          <input aria-label="North angle" type="number" step="1" min={0} max={359} style={field} disabled={!edit} value={p.site.north_deg} onChange={(e) => p.onSite({ ...p.site, north_deg: ((num(e.target.value, 0) % 360) + 360) % 360 })} />
        </label>
        {loc && edit && <button onClick={() => p.onSite({ ...p.site, location: null })}>Clear location</button>}
        {!loc && <div>No location: default lighting.</div>}
      </fieldset>
      <fieldset style={{ marginTop: 6 }}>
        <legend>Sun (this view only)</legend>
        <label>
          Date <input aria-label="Date" type="date" value={p.sun.date} onChange={(e) => e.target.value && p.onSun({ ...p.sun, date: e.target.value })} />
        </label>
        <div>
          <label>
            Time {hhmm(p.sun.hours)}{" "}
            <input aria-label="Time of day" type="range" min={0} max={24} step={0.25} value={p.sun.hours} onChange={(e) => p.onSun({ ...p.sun, hours: Number(e.target.value) })} />
          </label>
        </div>
        <label>
          UTC offset (h){" "}
          <input aria-label="UTC offset" type="number" min={-12} max={14} step={0.5} style={field} value={p.sun.utcOffset} onChange={(e) => p.onSun({ ...p.sun, utcOffset: Math.max(-12, Math.min(14, num(e.target.value, 0))) })} />
        </label>
        <div>
          <label>
            Sun intensity {p.sun.intensity.toFixed(1)}{" "}
            <input aria-label="Sun intensity" type="range" min={0} max={2} step={0.1} value={p.sun.intensity} onChange={(e) => p.onSun({ ...p.sun, intensity: Number(e.target.value) })} />
          </label>
        </div>
        {p.sunInfo && <div>{p.sunInfo}</div>}
      </fieldset>
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
