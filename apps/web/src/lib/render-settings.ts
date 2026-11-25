// Settings and stop logic of the path-traced still and the screenshot, free of WebGL so they can be tested.
export type ResolutionId = "viewport" | "1080p" | "4k";
export const RESOLUTIONS: Record<ResolutionId, { label: string; longEdge: number | null }> = {
  viewport: { label: "Viewport", longEdge: null },
  "1080p": { label: "1080p (1920 px long edge)", longEdge: 1920 },
  "4k": { label: "4K (3840 px long edge)", longEdge: 3840 },
};
export const RESOLUTION_IDS = Object.keys(RESOLUTIONS) as ResolutionId[];

export const SAMPLE_LIMITS = { min: 1, max: 2000, default: 200 };
export const TIME_LIMITS = { max: 3600 }; // seconds; 0 = no time limit
export const MAX_TRIANGLES = 2_000_000; // above this the BVH build would freeze the page: refuse with a message

export type TraceSettings = { samples: number; timeLimitSec: number; resolution: ResolutionId };
export const DEFAULT_TRACE: TraceSettings = { samples: SAMPLE_LIMITS.default, timeLimitSec: 0, resolution: "viewport" };

const clampInt = (v: number, lo: number, hi: number, fallback: number) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, Math.round(v))) : fallback);

/** Keep user input inside what the tracer can do (NaN and out-of-range values never reach it). */
export function clampTrace(s: TraceSettings): TraceSettings {
  return {
    samples: clampInt(s.samples, SAMPLE_LIMITS.min, SAMPLE_LIMITS.max, SAMPLE_LIMITS.default),
    timeLimitSec: clampInt(s.timeLimitSec, 0, TIME_LIMITS.max, 0),
    resolution: RESOLUTION_IDS.includes(s.resolution) ? s.resolution : "viewport",
  };
}

/** Output size in px: the preset's long edge (or the viewport) with the viewport's aspect ratio, shrunk to
 *  fit the GPU's largest drawing buffer. `clamped` tells the panel the request was reduced. */
export function outputSize(res: ResolutionId, viewport: { w: number; h: number }, maxDim: number): { w: number; h: number; clamped: boolean } {
  const vw = Math.max(1, Math.round(viewport.w));
  const vh = Math.max(1, Math.round(viewport.h));
  const long = RESOLUTIONS[res].longEdge ?? Math.max(vw, vh);
  const limit = Math.max(16, Math.floor(maxDim));
  const target = Math.min(long, limit);
  const k = target / Math.max(vw, vh);
  return { w: Math.max(1, Math.round(vw * k)), h: Math.max(1, Math.round(vh * k)), clamped: target < long };
}

export type StopReason = "samples" | "time" | "user";
export type TraceProgress = { samples: number; elapsedMs: number };

/** Stop at whichever limit is reached first; null while it should keep sampling. */
export function stopReason(p: TraceProgress, s: TraceSettings): StopReason | null {
  if (p.samples >= s.samples) return "samples";
  if (s.timeLimitSec > 0 && p.elapsedMs >= s.timeLimitSec * 1000) return "time";
  return null;
}

/** 0..1 for the progress bar: the nearer of the two limits. */
export function progressOf(p: TraceProgress, s: TraceSettings): number {
  const bySamples = p.samples / s.samples;
  const byTime = s.timeLimitSec > 0 ? p.elapsedMs / (s.timeLimitSec * 1000) : 0;
  return Math.min(1, Math.max(bySamples, byTime));
}

export const stillName = (stem: string, w: number, h: number, kind: string) => `${stem.replace(/[^A-Za-z0-9_-]+/g, "_") || "model"}-${kind}-${w}x${h}.png`;

// What the path-traced still approximates, shown in the panel so nothing is hidden.
export const TRACE_NOTES = [
  "Glass and other see-through parts are traced as semi-transparent (no refraction).",
  "Only the sun, point and spot lights and a plain sky are traced; the viewer's walk-mode fill light and reflections preset are not.",
  "Accuracy quality traces the flat palette without textures.",
];
