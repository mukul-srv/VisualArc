import { expect, test as setup } from "@playwright/test";

// Log in once through the API (no UI typing) and save one state file per role.
// Every e2e run and playwright-cli session starts from these files; a login page means they expired: rerun this project.
for (const role of ["owner", "viewer"]) {
  setup(`auth ${role}`, async ({ request }) => {
    const creds = { email: `${role}@e2e.test`, password: process.env.E2E_PASSWORD ?? "e2e-password-1234" };
    const reg = await request.post("/api/v1/auth/register", { data: { ...creds, display_name: `E2E ${role}` } });
    expect([201, 409]).toContain(reg.status());
    const res = await request.post("/api/v1/auth/login", { data: creds });
    expect(res.ok()).toBeTruthy();
    await request.storageState({ path: `e2e/.auth/${role}.json` });
  });
}
