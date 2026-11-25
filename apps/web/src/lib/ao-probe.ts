/** Sample points (0..1 across the frame) used to check that the ambient-occlusion frame is not black. */
export const PROBE_GRID = 8;
export const probePoints = (): [number, number][] =>
  Array.from({ length: PROBE_GRID * PROBE_GRID }, (_, i) => [((i % PROBE_GRID) + 0.5) / PROBE_GRID, (Math.floor(i / PROBE_GRID) + 0.5) / PROBE_GRID]);

/** A frame is unusable when every sampled pixel is (near) black: the viewer's background alone is about 30,
 *  and lit surfaces are brighter, so an all-black grid means the AO pass broke the image (RGBA bytes in). */
export function frameUsable(rgba: ArrayLike<number>, threshold = 8): boolean {
  for (let i = 0; i < rgba.length; i += 4) if (Math.max(rgba[i], rgba[i + 1], rgba[i + 2]) >= threshold) return true;
  return false;
}
