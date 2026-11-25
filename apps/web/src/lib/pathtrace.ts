import { progressOf, stopReason, type StopReason, type TraceSettings } from "./render-settings";

// Drives a progressive path tracer until a limit is reached. The tracer is injected (the real one is
// three-gpu-pathtracer's WebGLPathTracer, loaded on demand), so this logic runs without WebGL.
export type Tracer = {
  readonly samples: number;
  readonly isCompiling?: boolean;
  renderSample(): void;
};
export type TraceStatus = { samples: number; elapsedMs: number; progress: number; compiling: boolean };
export type Schedule = { now: () => number; request: (cb: () => void) => number; cancel: (id: number) => void };

export const browserSchedule: Schedule = {
  now: () => performance.now(),
  request: (cb) => requestAnimationFrame(cb),
  cancel: (id) => cancelAnimationFrame(id),
};

/** One sample per frame (the tracer renders tiles itself, so the page stays responsive). The time limit
 *  counts from the first sample, not from the shader compile. `done` resolves once, with why it stopped;
 *  a throwing tracer rejects it (the caller shows the message and disposes). */
export function runTrace(tracer: Tracer, settings: TraceSettings, schedule: Schedule, onStatus: (s: TraceStatus) => void) {
  let handle = 0;
  let stopped = false;
  let t0: number | null = null;
  let finish: (r: StopReason) => void = () => {};
  let fail: (e: unknown) => void = () => {};
  const done = new Promise<StopReason>((res, rej) => {
    finish = res;
    fail = rej;
  });
  const status = (): TraceStatus => {
    const p = { samples: tracer.samples, elapsedMs: t0 === null ? 0 : schedule.now() - t0 };
    return { ...p, progress: progressOf(p, settings), compiling: !!tracer.isCompiling };
  };
  const frame = () => {
    if (stopped) return;
    try {
      tracer.renderSample();
      if (t0 === null && tracer.samples > 0) t0 = schedule.now();
      const st = status();
      onStatus(st);
      const why = stopReason(st, settings);
      if (why) {
        stopped = true;
        return finish(why);
      }
    } catch (e) {
      stopped = true;
      return fail(e);
    }
    handle = schedule.request(frame);
  };
  handle = schedule.request(frame);
  return {
    done,
    stop() {
      if (stopped) return;
      stopped = true;
      schedule.cancel(handle);
      onStatus(status());
      finish("user");
    },
  };
}

/** Thrown when the panel was closed while the tracer was still being built. */
export const CANCELLED = new Error("path tracing was cancelled");
export const checkpoint = (isCancelled: () => boolean) => {
  if (isCancelled()) throw CANCELLED;
};

/** Cancel token: `next()` starts an operation, `cancel()` makes every earlier one report cancelled. */
export function cancelToken() {
  let n = 0;
  return { next: () => ++n, cancel: () => void n++, isCurrent: (id: number) => id === n };
}

export type Session = { done: Promise<StopReason>; stop: () => void; dispose: () => void };

/** Build, then sample. `dispose` always stops the sampling loop first, so a closed panel never leaves a
 *  frame loop running on freed GPU resources. If cancelled while `prepare` was awaiting, everything it made
 *  is freed and nothing starts. */
export async function startTrace(
  prepare: () => Promise<{ tracer: Tracer; free: () => void }>,
  settings: TraceSettings,
  schedule: Schedule,
  onStatus: (s: TraceStatus) => void,
  isCancelled: () => boolean,
): Promise<Session> {
  const built = await prepare();
  if (isCancelled()) {
    built.free();
    throw CANCELLED;
  }
  const run = runTrace(built.tracer, settings, schedule, onStatus);
  let freed = false;
  return {
    done: run.done,
    stop: run.stop,
    dispose: () => {
      run.stop();
      if (!freed) built.free();
      freed = true;
    },
  };
}
