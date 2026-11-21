import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { RetryNotice } from "./RequireAuth";

test("a failed sign-in check shows the error and a Retry button", () => {
  const html = renderToStaticMarkup(<RetryNotice message="Cannot reach the API. Is the backend running?" onRetry={() => {}} />);
  expect(html).toContain('role="alert"');
  expect(html).toContain("Cannot reach the API");
  expect(html).toMatch(/<button[^>]*>Retry<\/button>/);
});
