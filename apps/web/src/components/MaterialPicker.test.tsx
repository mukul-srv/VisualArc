import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { MaterialPicker } from "./MaterialPicker";

const render = (disabled: boolean, value: string | null = null) =>
  renderToStaticMarkup(<MaterialPicker type="wall" value={value} disabled={disabled} onChange={() => {}} />);

test("editors get a select with default and the materials suiting the type", () => {
  const html = render(false, "brick");
  expect(html).toContain("<select");
  expect(html).toContain(">default<");
  expect(html).toContain(">Brick<");
  expect(html).not.toContain("Roof tiles");
});

test("viewers see the applied material but get no control", () => {
  const html = render(true, "brick");
  expect(html).not.toContain("<select");
  expect(html).toContain("Material: Brick");
  expect(render(true)).toContain("Material: default");
});
