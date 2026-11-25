import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { IDLE_RENDER, RenderPanel, type RenderState } from "./RenderPanel";
import { DEFAULT_TRACE } from "../lib/render-settings";

const render = (state: RenderState) =>
  renderToStaticMarkup(<RenderPanel state={state} settings={DEFAULT_TRACE} onSettings={() => {}} onStart={() => {}} onStop={() => {}} onScreenshot={() => {}} onClose={() => {}} />);

test("idle: settings, start, screenshot and the approximation notes are shown", () => {
  const html = render(IDLE_RENDER);
  expect(html).toContain("Start render");
  expect(html).toContain("Screenshot (realtime PNG)");
  expect(html).toContain("1080p");
  expect(html).toContain("semi-transparent");
  expect(html).not.toContain(">Stop<");
});

test("running: live counter and progress, settings locked, stop offered", () => {
  const html = render({ ...IDLE_RENDER, phase: "running", status: { samples: 40, elapsedMs: 12000, progress: 0.2, compiling: false } });
  expect(html).toContain(">Stop<");
  expect(html).toContain("40 / 200 samples");
  expect(html).toContain("12.0 s");
  expect(html).toMatch(/<fieldset[^>]*disabled/);
});

test("error and done states", () => {
  expect(render({ ...IDLE_RENDER, phase: "error", message: "Path tracing failed: no float textures" })).toContain("no float textures");
  const done = render({ ...IDLE_RENDER, phase: "done", size: { w: 800, h: 600 }, result: { url: "blob:x", name: "a-render-800x600.png", kind: "render" } });
  expect(done).toContain('download="a-render-800x600.png"');
  expect(done).toContain("800 x 600");
});
