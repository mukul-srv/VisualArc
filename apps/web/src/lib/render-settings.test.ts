import { expect, test, vi } from "vitest";
import { runTrace, type Schedule, type Tracer } from "./pathtrace";
import { clampTrace, DEFAULT_TRACE, outputSize, progressOf, SAMPLE_LIMITS, stillName, stopReason } from "./render-settings";

test("output size keeps the viewport aspect and clamps to the GPU maximum", () => {
  const vp = { w: 1000, h: 500 };
  expect(outputSize("viewport", vp, 16384)).toEqual({ w: 1000, h: 500, clamped: false });
  expect(outputSize("1080p", vp, 16384)).toEqual({ w: 1920, h: 960, clamped: false });
  expect(outputSize("4k", { w: 500, h: 1000 }, 16384)).toEqual({ w: 1920, h: 3840, clamped: false });
  expect(outputSize("4k", vp, 2048)).toEqual({ w: 2048, h: 1024, clamped: true });
  expect(outputSize("viewport", { w: 5000, h: 100 }, 2048)).toEqual({ w: 2048, h: 41, clamped: true });
  const tiny = outputSize("viewport", { w: 0, h: 0 }, 4);
  expect(tiny.w).toBeGreaterThan(0);
  expect(tiny.h).toBeGreaterThan(0);
});

test("settings are clamped; NaN falls back", () => {
  expect(clampTrace({ samples: 1e9, timeLimitSec: -5, resolution: "4k" })).toEqual({ samples: SAMPLE_LIMITS.max, timeLimitSec: 0, resolution: "4k" });
  expect(clampTrace({ samples: 0, timeLimitSec: 1e9, resolution: "bad" as never })).toEqual({ samples: 1, timeLimitSec: 3600, resolution: "viewport" });
  expect(clampTrace({ samples: NaN, timeLimitSec: NaN, resolution: "viewport" })).toEqual(DEFAULT_TRACE);
});

test("stops at whichever limit comes first", () => {
  const s = { samples: 100, timeLimitSec: 10, resolution: "viewport" as const };
  expect(stopReason({ samples: 50, elapsedMs: 9999 }, s)).toBeNull();
  expect(stopReason({ samples: 100, elapsedMs: 1 }, s)).toBe("samples");
  expect(stopReason({ samples: 5, elapsedMs: 10000 }, s)).toBe("time");
  expect(stopReason({ samples: 99, elapsedMs: 1e9 }, { ...s, timeLimitSec: 0 })).toBeNull(); // 0 = no time limit
  expect(progressOf({ samples: 25, elapsedMs: 5000 }, s)).toBe(0.5);
  expect(progressOf({ samples: 500, elapsedMs: 0 }, s)).toBe(1);
});

test("file names are safe", () => {
  expect(stillName("My House/1", 1920, 1080, "render")).toBe("My_House_1-render-1920x1080.png");
  expect(stillName("", 10, 10, "shot")).toBe("model-shot-10x10.png");
});

function fake() {
  let t = 0;
  const queue: (() => void)[] = [];
  const schedule: Schedule = { now: () => t, request: (cb) => queue.push(cb), cancel: () => queue.splice(0) };
  const step = (ms: number) => {
    t += ms;
    queue.splice(0).forEach((cb) => cb());
  };
  return { schedule, step };
}

test("runTrace samples until the sample target, then resolves once", async () => {
  const { schedule, step } = fake();
  const tracer = { samples: 0, renderSample: vi.fn(() => void tracer.samples++) } as Tracer & { samples: number };
  const seen: number[] = [];
  const run = runTrace(tracer, { samples: 3, timeLimitSec: 0, resolution: "viewport" }, schedule, (s) => seen.push(s.samples));
  for (let i = 0; i < 5; i++) step(16);
  expect(await run.done).toBe("samples");
  expect(tracer.renderSample).toHaveBeenCalledTimes(3);
  expect(seen).toEqual([1, 2, 3]);
});

test("the time limit counts from the first sample, not the compile", async () => {
  const { schedule, step } = fake();
  let compiling = true;
  const tracer = { get samples() { return compiling ? 0 : 1; }, get isCompiling() { return compiling; }, renderSample: vi.fn() } as Tracer;
  const run = runTrace(tracer, { samples: 1000, timeLimitSec: 1, resolution: "viewport" }, schedule, () => {});
  step(5000); // compiling for 5 s: no time used
  compiling = false;
  step(16); // first sample: clock starts
  step(500);
  let result: string | undefined;
  void run.done.then((r) => (result = r));
  await Promise.resolve();
  expect(result).toBeUndefined();
  step(600);
  expect(await run.done).toBe("time");
});

test("stop() ends it as 'user'; a tracer that throws rejects done", async () => {
  const a = fake();
  const t1 = { samples: 0, renderSample() {} } as Tracer;
  const run = runTrace(t1, DEFAULT_TRACE, a.schedule, () => {});
  a.step(16);
  run.stop();
  expect(await run.done).toBe("user");
  const b = fake();
  const bad: Tracer = { samples: 0, renderSample() { throw new Error("float textures unsupported"); } };
  const r2 = runTrace(bad, DEFAULT_TRACE, b.schedule, () => {});
  b.step(16);
  await expect(r2.done).rejects.toThrow("float textures");
});
