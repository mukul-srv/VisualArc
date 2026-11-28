import path from "node:path";
import { expect, type Page } from "@playwright/test";

const FIXTURE = path.resolve(__dirname, "../../../fixtures/input/fixture_a.dxf");

/** Upload fixture_a.dxf through the UI and land in the viewer (a standalone generation). */
export async function generateFixture(page: Page) {
  await page.goto("/new");
  await page.getByLabel("Floor plan file").setInputFiles(FIXTURE);
  await page.getByRole("button", { name: "Check my plan", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review before saving" })).toBeVisible({ timeout: 90_000 });
  await page.getByRole("button", { name: "Create 3D model" }).click();
  await expect(page).toHaveURL(/\/viewer/, { timeout: 90_000 });
}

/** Generate, then save the newest standalone model as a uniquely named project; returns its id. */
export async function createProject(page: Page, name: string) {
  await generateFixture(page);
  await page.goto("/");
  const newest = page.getByRole("list", { name: "Unsaved models" }).getByRole("listitem").first();
  await newest.getByRole("button", { name: "Save as project" }).click();
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+$/);
  return page.url().split("/projects/")[1].split(/[?#]/)[0];
}
