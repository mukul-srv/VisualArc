import { expect, test } from "vitest";
import { createTapGate, isDoubleTap } from "./tap";

test("two quick, close taps are a double tap; slow, far or lone ones are not", () => {
  const a = { t: 1000, x: 100, y: 100 };
  expect(isDoubleTap(a, { t: 1200, x: 105, y: 98 })).toBe(true);
  expect(isDoubleTap(a, { t: 1500, x: 100, y: 100 })).toBe(false);
  expect(isDoubleTap(a, { t: 1100, x: 200, y: 100 })).toBe(false);
  expect(isDoubleTap(null, a)).toBe(false);
});

// A fake clock so the gate is tested without waiting.
function clock() {
  let now = 0;
  const timers: { at: number; f: () => void; id: number; live: boolean }[] = [];
  return {
    set: (f: () => void, ms: number) => {
      const t = { at: now + ms, f, id: timers.length, live: true };
      timers.push(t);
      return t;
    },
    clear: (t: unknown) => ((t as { live: boolean }).live = false),
    advance(ms: number) {
      now += ms;
      for (const t of timers) if (t.live && t.at <= now) { t.live = false; t.f(); }
    },
    now: () => now,
  };
}

test("a single click runs after the delay; a double click runs only the double action", () => {
  const c = clock();
  const gate = createTapGate(250, c);
  const log: string[] = [];
  gate.tap({ t: c.now(), x: 10, y: 10 }, () => log.push("single"), () => log.push("double"));
  expect(log).toEqual([]); // waiting
  c.advance(249);
  expect(log).toEqual([]);
  c.advance(2);
  expect(log).toEqual(["single"]); // responsive enough: fires at the delay

  log.length = 0;
  gate.tap({ t: c.now(), x: 10, y: 10 }, () => log.push("single"), () => log.push("double"));
  c.advance(120);
  const r = gate.tap({ t: c.now(), x: 12, y: 11 }, () => log.push("single2"), () => log.push("double"));
  expect(r).toBe("double");
  c.advance(1000);
  expect(log).toEqual(["double"]); // the first click's selection was cancelled: no highlight, no panel
});

test("a second tap far away or too late is a new click, and the pending one runs first", () => {
  const c = clock();
  const gate = createTapGate(250, c);
  const log: string[] = [];
  gate.tap({ t: 0, x: 10, y: 10 }, () => log.push("a"), () => log.push("double"));
  c.advance(100);
  gate.tap({ t: c.now(), x: 300, y: 10 }, () => log.push("b"), () => log.push("double")); // elsewhere
  expect(log).toEqual(["a"]);
  c.advance(300);
  expect(log).toEqual(["a", "b"]);
  gate.tap({ t: c.now(), x: 5, y: 5 }, () => log.push("c"), () => log.push("double"));
  gate.cancel();
  c.advance(1000);
  expect(log).toEqual(["a", "b"]); // cancelled: nothing fires
});
