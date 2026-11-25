// Render quality presets as data. Accuracy is the flat measured look: no textures, shadows, ambient
// occlusion or reflections, the plain default palette and default lights, so measurements read true.
export type QualityId = "low" | "medium" | "high" | "accuracy";
export type Quality = {
  label: string;
  shadowMap: number; // px; 0 = no shadows
  ssao: boolean;
  env: boolean; // procedural room reflections
  textures: boolean;
  artificial: boolean; // user lights and location-driven sun (off: default lights)
  pixelRatioMax: number;
};

export const QUALITY: Record<QualityId, Quality> = {
  low: { label: "Low", shadowMap: 0, ssao: false, env: false, textures: true, artificial: true, pixelRatioMax: 1 },
  medium: { label: "Medium", shadowMap: 1024, ssao: false, env: true, textures: true, artificial: true, pixelRatioMax: 1.5 },
  high: { label: "High", shadowMap: 2048, ssao: true, env: true, textures: true, artificial: true, pixelRatioMax: 2 },
  accuracy: { label: "Accuracy", shadowMap: 0, ssao: false, env: false, textures: false, artificial: false, pixelRatioMax: 1.5 },
};
export const QUALITY_IDS = Object.keys(QUALITY) as QualityId[];
export const DEFAULT_QUALITY: QualityId = "medium";

/** Half-extent (m) and centre of a square shadow frustum that covers a building's bounds from any sun angle. */
export function shadowFrustum(min: [number, number, number], max: [number, number, number]) {
  const c: [number, number, number] = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
  const r = Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2 || 1;
  return { centre: c, radius: r };
}
