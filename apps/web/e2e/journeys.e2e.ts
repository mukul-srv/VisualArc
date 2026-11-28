import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "./a11y";
import { createProject, generateFixture } from "./helpers";

// Known axe finding on the untouched dashboard and project pages: <details> summaries are under 24px (WCAG 2.5.8 target-size).
const KNOWN_SUMMARY_SIZE = ["target-size"];
const uid = () => `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

test("dashboard: owner sees projects heading and main nav", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "My projects", level: 1 })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Projects" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "New project" })).toBeVisible();
  await expect(nav.getByText("Account")).toBeVisible();
  await expectNoA11yViolations(page, KNOWN_SUMMARY_SIZE);
});

test("upload: review then accept lands in the viewer", async ({ page }) => {
  await generateFixture(page);
  await expect(page.getByRole("toolbar", { name: "Viewer tools" })).toBeVisible({ timeout: 60_000 });
});

test("save as project, then project page for the owner", async ({ page }) => {
  const name = uid();
  await createProject(page, name);
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
  for (const tab of ["Floors", "Parameters", "Versions", "Sharing"]) {
    await expect(page.getByRole("tab", { name: tab })).toBeVisible();
  }
  // one floor: the floor row opens the viewer (the toolbar no longer repeats it); Rename sits by the title, Share in the toolbar
  await expect(page.getByRole("list", { name: "Floors" }).getByRole("link", { name: "View in 3D" })).toBeVisible();
  await expect(page.getByRole("toolbar", { name: "Project actions" }).getByRole("button", { name: "Delete" })).toBeVisible(); // no More menu: Delete is the only item
  await expect(page.getByRole("button", { name: "Share" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Rename" })).toBeVisible();
  await expectNoA11yViolations(page, KNOWN_SUMMARY_SIZE);
});

test.describe("viewer role", () => {
  test.use({ storageState: "e2e/.auth/viewer.json" });

  test("sees view-only banner on a project shared with them", async ({ page, browser }) => {
    // set up with the owner: own project, shared to the viewer account through the API
    const owner = await browser.newContext({ storageState: "e2e/.auth/owner.json" });
    const ownerPage = await owner.newPage();
    const id = await createProject(ownerPage, uid());
    const res = await owner.request.put(`/api/v1/projects/${id}/access`, { data: { email: "viewer@e2e.test", role: "viewer" } });
    expect(res.ok()).toBeTruthy();
    await owner.close();

    await page.goto(`/projects/${id}`);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText("You have view-only access to this project.")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Sharing" })).toHaveCount(0);
    await expectNoA11yViolations(page, KNOWN_SUMMARY_SIZE);
  });
});

test("profile: heading, display name, log out", async ({ page }) => {
  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Profile", level: 1 })).toBeVisible();
  await expect(page.getByLabel("Display name")).toBeVisible();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await expectNoA11yViolations(page);
});

test.describe("unauthenticated", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("login: form fields and error on empty submit", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Log in", level: 1 })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expectNoA11yViolations(page);
    await page.getByRole("button", { name: "Log in" }).click();
    // the inputs are `required`: native validation blocks submit (the app shows no alert of its own)
    await expect(page.getByLabel("Email")).toHaveJSProperty("validity.valueMissing", true);
    await expect(page).toHaveURL(/\/login/);
  });
});
