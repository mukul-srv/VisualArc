import { API_BASE, send } from "./api";

// The project's saved lighting setting (PUT /projects/{id}/lighting): site location, building north and
// artificial lights. Date, time, sun intensity and quality are viewer-local and never saved.
export type LightKind = "point" | "spot";
export type ArtificialLight = {
  id: string;
  kind: LightKind;
  floor_id: string;
  x_mm: number; // plan position before the floor offset
  y_mm: number;
  height_mm: number; // above the floor's elevation
  color: string; // #rrggbb
  intensity: number;
};
export type SiteLighting = { location: { latitude: number; longitude: number } | null; north_deg: number; lights: ArtificialLight[] };
export const NO_LIGHTING: SiteLighting = { location: null, north_deg: 0, lights: [] };
export const MAX_LIGHTS = 50;

const num = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** Untrusted manifest/building value -> a valid setting (malformed parts dropped, never thrown). */
export function parseLighting(x: unknown): SiteLighting {
  const v = x as Partial<SiteLighting> | null;
  if (!v || typeof v !== "object") return NO_LIGHTING;
  const loc = v.location;
  const location = loc && num(loc.latitude) && num(loc.longitude) && Math.abs(loc.latitude) <= 90 && Math.abs(loc.longitude) <= 180 ? { latitude: loc.latitude, longitude: loc.longitude } : null;
  const lights = (Array.isArray(v.lights) ? v.lights : []).filter(
    (l): l is ArtificialLight =>
      !!l && typeof l.id === "string" && (l.kind === "point" || l.kind === "spot") && typeof l.floor_id === "string" && num(l.x_mm) && num(l.y_mm) && num(l.height_mm) && /^#[0-9a-fA-F]{6}$/.test(l.color) && num(l.intensity),
  ).map((l) => ({ ...l, intensity: Math.min(10, Math.max(0, l.intensity)) })); // old saves allowed up to 100: clamp, never drop
  return { location, north_deg: num(v.north_deg) ? ((v.north_deg % 360) + 360) % 360 : 0, lights: lights.slice(0, MAX_LIGHTS) };
}

/** Next free light id ("light-N"). */
export const nextLightId = (lights: ArtificialLight[]) => {
  const used = new Set(lights.map((l) => l.id));
  for (let i = 1; ; i++) if (!used.has(`light-${i}`)) return `light-${i}`;
};

export const putLighting = (pid: string, lighting: SiteLighting, f: typeof fetch = fetch) =>
  send<{ lighting: SiteLighting; version: number }>(() =>
    f(`${API_BASE}/api/v1/projects/${pid}/lighting`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lighting),
    }),
  );

/** World map click (equirectangular, `world.svg` viewBox 360 x 180) -> lat/lon, rounded to 0.1 degree. */
export function mapClickToLatLon(fx: number, fy: number): { latitude: number; longitude: number } {
  const r = (v: number) => Math.round(v * 10) / 10;
  return { latitude: r(90 - Math.max(0, Math.min(1, fy)) * 180), longitude: r(Math.max(0, Math.min(1, fx)) * 360 - 180) };
}
