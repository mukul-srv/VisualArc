// Double click / double tap for the canvas: touch has no reliable `dblclick` once OrbitControls takes
// the pointer, so two quick, close taps are detected by hand.
export type Tap = { t: number; x: number; y: number };

export const DOUBLE_TAP = { ms: 350, px: 24 };

export function isDoubleTap(prev: Tap | null, cur: Tap): boolean {
  return !!prev && cur.t - prev.t <= DOUBLE_TAP.ms && Math.hypot(cur.x - prev.x, cur.y - prev.y) <= DOUBLE_TAP.px;
}
