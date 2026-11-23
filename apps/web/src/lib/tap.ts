// Double click / double tap for the canvas: touch has no reliable `dblclick` once OrbitControls takes
// the pointer, so two quick, close taps are detected by hand.
export type Tap = { t: number; x: number; y: number };

export const DOUBLE_TAP = { ms: 350, px: 24 };

export function isDoubleTap(prev: Tap | null, cur: Tap): boolean {
  return !!prev && cur.t - prev.t <= DOUBLE_TAP.ms && Math.hypot(cur.x - prev.x, cur.y - prev.y) <= DOUBLE_TAP.px;
}

type Timers = { set: (f: () => void, ms: number) => unknown; clear: (id: unknown) => void };
const REAL: Timers = { set: (f, ms) => setTimeout(f, ms), clear: (id) => clearTimeout(id as ReturnType<typeof setTimeout>) };

export const SINGLE_DELAY_MS = 250;

/** Single click vs double click on the same target. A single click runs after `delay` ms unless a
 *  second quick, close tap arrives first: then only `onDouble` runs, so a double click on a door
 *  does not also select it and open its properties. A tap far from (or after) the pending one runs
 *  the pending single at once and starts a new wait. */
export function createTapGate(delay = SINGLE_DELAY_MS, timers: Timers = REAL) {
  let pending: { tap: Tap; id: unknown; single: () => void } | null = null;
  const flush = () => {
    if (!pending) return;
    timers.clear(pending.id);
    const { single } = pending;
    pending = null;
    single();
  };
  return {
    tap(tap: Tap, onSingle: () => void, onDouble: () => void): "wait" | "double" {
      if (pending && isDoubleTap(pending.tap, tap)) {
        timers.clear(pending.id);
        pending = null;
        onDouble();
        return "double";
      }
      flush();
      const entry = { tap, single: onSingle, id: null as unknown };
      entry.id = timers.set(() => {
        if (pending === entry) pending = null;
        onSingle();
      }, delay);
      pending = entry;
      return "wait";
    },
    cancel() {
      if (pending) timers.clear(pending.id);
      pending = null;
    },
  };
}
