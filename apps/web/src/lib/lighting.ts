// The viewer's lights as data, so what a surface looks like under them can be tested without WebGL.
//
// Root cause of "the roof is invisible in walk mode": the roof's underside faces DOWN, the only light
// reaching it is the hemisphere light's dark ground colour, and the roof's own colour is dark
// brown: it rendered at about the background colour (headless render of the real model: pixel 28,19,22
// against a background of 30,30,34), so nothing could be told apart. Walking inside needs a fill light.

export type Light =
  | { kind: "hemisphere"; sky: number; ground: number; intensity: number }
  | { kind: "ambient"; color: number; intensity: number }
  | { kind: "directional"; color: number; intensity: number; dir: [number, number, number] };

export const BACKGROUND = 0x1e1e22;
/** Lights of the orbit view (the viewer adds exactly these). */
export const BASE_LIGHTS: Light[] = [
  { kind: "hemisphere", sky: 0xffffff, ground: 0x444455, intensity: 1.2 },
  { kind: "directional", color: 0xffffff, intensity: 1.5, dir: [5, 10, 5] },
];
/** Added in walk mode: inside, down-facing surfaces (roof underside, ceilings) get no sun or sky. */
export const WALK_FILL: Light = { kind: "ambient", color: 0xffffff, intensity: 0.9 };

const rgb = (hex: number): [number, number, number] => [(hex >> 16) & 255, (hex >> 8) & 255, hex & 255].map((v) => v / 255) as [number, number, number];
const luminance = ([r, g, b]: [number, number, number]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;

/** Approximate colour (0..1 per channel, linear-ish) of a diffuse surface with `albedo` whose unit
 *  `normal` faces the viewer, under `lights`. Same terms as three's diffuse shading: hemisphere blends
 *  ground to sky by the normal's up component, ambient is flat, a directional light needs a facing normal. */
export function shade(albedo: number, normal: [number, number, number], lights: Light[]): [number, number, number] {
  const a = rgb(albedo);
  const sum: [number, number, number] = [0, 0, 0];
  for (const l of lights) {
    let e: [number, number, number];
    if (l.kind === "hemisphere") {
      const t = 0.5 + 0.5 * normal[1];
      const s = rgb(l.sky), g = rgb(l.ground);
      e = [0, 1, 2].map((i) => (g[i] + (s[i] - g[i]) * t) * l.intensity) as [number, number, number];
    } else if (l.kind === "ambient") {
      e = rgb(l.color).map((v) => v * l.intensity) as [number, number, number];
    } else {
      const len = Math.hypot(...l.dir);
      const d = Math.max(0, (normal[0] * l.dir[0] + normal[1] * l.dir[1] + normal[2] * l.dir[2]) / len);
      e = rgb(l.color).map((v) => v * l.intensity * d) as [number, number, number];
    }
    for (let i = 0; i < 3; i++) sum[i] += e[i];
  }
  return [0, 1, 2].map((i) => Math.min(1, a[i] * sum[i])) as [number, number, number];
}

/** How many times brighter than the background a surface is (below 1: darker, hard to see). */
export const contrastWithBackground = (surface: [number, number, number]) => luminance(surface) / luminance(rgb(BACKGROUND));
