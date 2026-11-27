import { expect, test } from "@playwright/test";

test("signed-in owner lands on the dashboard, not the login page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page).not.toHaveURL(/\/login/);
});
