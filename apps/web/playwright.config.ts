import { mkdirSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

mkdirSync("e2e-results", { recursive: true });
const ci = !!process.env.CI;
// API runs against a scratch DB (DATABASE_URL from the environment, never `visual_arc`); output goes to a file, not the agent's context.
const api = "uv run uvicorn api.main:app --port 8000 > ../../apps/web/e2e-results/api.log 2>&1";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "e2e-results/artifacts",
  reporter: [["line"], ["json", { outputFile: "e2e-results/results.json" }]],
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "setup", testMatch: /.*\.setup\.ts/ },
    {
      name: "chromium",
      dependencies: ["setup"],
      testMatch: /.*\.e2e\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/owner.json" },
    },
  ],
  webServer: [
    {
      command: api,
      cwd: "../../services/api",
      env: { AUTH_RATE_LIMIT_PER_MIN: "200" },
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: !ci,
      timeout: 120_000,
    },
    { command: "npm run dev", url: "http://localhost:3000", reuseExistingServer: !ci, stdout: "ignore", timeout: 120_000 },
  ],
});
