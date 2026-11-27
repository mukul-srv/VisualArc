import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "./a11y";
import { createProject, generateFixture } from "./helpers";

const KNOWN_SUMMARY_SIZE = ["target-size"]; // <details> summaries under 24px, see journeys.e2e.ts

test("404: page not found with a way back", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { name: "Page not found", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to projects" })).toBeVisible();
  await expectNoA11yViolations(page);
});

test("project page: owner Share button opens the Sharing tab", async ({ page }) => {
  await createProject(page, `e2e-${Date.now()}`);
  await page.getByRole("toolbar", { name: "Project actions" }).getByRole("button", { name: "Share" }).click();
  await expect(page.getByRole("tab", { name: "Sharing" })).toHaveAttribute("aria-selected", "true");
  await expectNoA11yViolations(page, KNOWN_SUMMARY_SIZE);
});

test("viewer: standalone generation shows the not-saved note and a Profile link", async ({ page }) => {
  await generateFixture(page);
  await expect(page.getByRole("note").filter({ hasText: "This model is not saved to a project yet." })).toBeVisible();
  await expect(page.getByRole("link", { name: "Profile" })).toBeVisible();
});

test("dashboard: project list failure shows an alert and Try again recovers", async ({ page }) => {
  let fail = true;
  await page.route("**/api/v1/projects", (route) => (fail && route.request().method() === "GET" ? route.abort() : route.continue()));
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: "Could not load your projects." })).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Try again" }).first().click();
  await expect(page.getByRole("alert").filter({ hasText: "Could not load your projects." })).toHaveCount(0);
});

test("signed in: /login redirects to next or the dashboard", async ({ page }) => {
  await page.goto("/login");
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto("/login?next=%2Fprofile");
  await expect(page).toHaveURL(/\/profile$/);
});
