import { fit, toPlan, toScreen, type Bounds, type Fit } from "./overlay";
import { MAX_LIGHTS, nextLightId, type ArtificialLight } from "./site-lighting";

// Pure logic of the light placer: a square plan of one floor where lights are placed, dragged and nudged.
// Plan coordinates are the floor's own millimetres (what the saved lights use); `offset` is the floor's
// manual plan offset, for views that draw floors in building coordinates (the floor model carries it itself).

export const NUDGE_MM = 100;
export const NUDGE_BIG_MM = 500;
const DEFAULT_SIDE = 10000;

/** A square around the drawn plan with `margin` (fraction of the side) on every side, so the plan is never
 *  stretched; an empty floor gets a default 10 m square. */
export function squareBounds(b: Bounds | null, margin = 0.08): Bounds {
  if (!b) return { minX: 0, minY: 0, maxX: DEFAULT_SIDE, maxY: DEFAULT_SIDE };
  const side = Math.max(b.maxX - b.minX, b.maxY - b.minY, 1) * (1 + 2 * margin);
  const cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
  return { minX: cx - side / 2, minY: cy - side / 2, maxX: cx + side / 2, maxY: cy + side / 2 };
}

export const squareFit = (sq: Bounds, px: number): Fit => fit(sq, px, px, 0);

/** Screen px in the square -> floor plan mm (rounded to a whole mm). */
export function clickToPlan(f: Fit, sx: number, sy: number, offset: [number, number] = [0, 0]): [number, number] {
  const [x, y] = toPlan(f, sx, sy);
  return [Math.round(x - offset[0]), Math.round(y - offset[1])];
}

export function planToScreen(f: Fit, x: number, y: number, offset: [number, number] = [0, 0]): [number, number] {
  return toScreen(f, x + offset[0], y + offset[1]);
}

export const clampTo = (sq: Bounds, x: number, y: number): [number, number] => [
  Math.round(Math.min(sq.maxX, Math.max(sq.minX, x))),
  Math.round(Math.min(sq.maxY, Math.max(sq.minY, y))),
];

/** Only editors place, move or remove lights, and only up to MAX_LIGHTS in total. */
export const canPlace = (canEdit: boolean, count: number) => canEdit && count < MAX_LIGHTS;

const DEFAULT_HEIGHT_MM = 2400; // a ceiling light

/** Add a light at (x, y) on a floor. Unchanged list when not allowed. Returns the new list and the new id. */
export function placeLight(lights: ArtificialLight[], floorId: string, x: number, y: number, sq: Bounds, canEdit: boolean): { lights: ArtificialLight[]; id: string | null } {
  if (!canPlace(canEdit, lights.length)) return { lights, id: null };
  const [cx, cy] = clampTo(sq, x, y);
  const id = nextLightId(lights);
  return { id, lights: [...lights, { id, kind: "point", floor_id: floorId, x_mm: cx, y_mm: cy, height_mm: DEFAULT_HEIGHT_MM, color: "#ffe9c4", intensity: 3 }] };
}

/** Move one light to (x, y), clamped to the square. Unchanged for viewers or an unknown id. */
export function moveLight(lights: ArtificialLight[], id: string, x: number, y: number, sq: Bounds, canEdit: boolean): ArtificialLight[] {
  if (!canEdit || !lights.some((l) => l.id === id)) return lights;
  const [cx, cy] = clampTo(sq, x, y);
  return lights.map((l) => (l.id === id ? { ...l, x_mm: cx, y_mm: cy } : l));
}

/** Typed x or y (mm) for one light: clamped to the plan square like a drag; blank or non-numeric input changes nothing. */
export function setLightCoord(lights: ArtificialLight[], id: string, axis: "x" | "y", raw: string, sq: Bounds, canEdit: boolean): ArtificialLight[] {
  const l = lights.find((k) => k.id === id);
  const v = Number(raw);
  if (!l || raw.trim() === "" || !Number.isFinite(v)) return lights;
  return axis === "x" ? moveLight(lights, id, v, l.y_mm, sq, canEdit) : moveLight(lights, id, l.x_mm, v, sq, canEdit);
}

/** Commit what was typed in an x/y box (on blur or Enter): the new list and the text the box should show
 *  afterwards (the clamped value; the current one again when the text was blank or not a number). */
export function commitCoord(lights: ArtificialLight[], id: string, axis: "x" | "y", draft: string, sq: Bounds, canEdit: boolean): { lights: ArtificialLight[]; text: string } {
  const next = setLightCoord(lights, id, axis, draft, sq, canEdit);
  const l = next.find((k) => k.id === id);
  return { lights: next, text: l ? String(axis === "x" ? l.x_mm : l.y_mm) : "" };
}

export const nudgeLight = (lights: ArtificialLight[], id: string, dx: number, dy: number, sq: Bounds, canEdit: boolean) => {
  const l = lights.find((x) => x.id === id);
  return l ? moveLight(lights, id, l.x_mm + dx, l.y_mm + dy, sq, canEdit) : lights;
};

/** Arrow key -> plan step (plan y points up, so ArrowUp is +y); null for other keys. */
export function arrowStep(key: string, big: boolean): [number, number] | null {
  const s = big ? NUDGE_BIG_MM : NUDGE_MM;
  return ({ ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, s], ArrowDown: [0, -s] } as Record<string, [number, number]>)[key] ?? null;
}
