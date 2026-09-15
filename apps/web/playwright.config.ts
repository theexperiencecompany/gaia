import { defineConfig, devices } from "@playwright/test";
import { WEB_BASE_URL } from "./e2e/harness";

/**
 * Playwright config for GAIA web e2e, run against an already-running dev stack
 * (`mise dev --sim`/`--agent`, both with dev auth bypass on) — no auth fixture
 * needed. `global-setup` mints + seeds the dev user for deterministic data;
 * ports come from WEB_PORT/API_PORT for per-worktree runs.
 */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 1 : undefined,
  // Target is always a Next.js DEV server, so the first route visit pays a
  // Turbopack compile (fullyParallel means every worker pays it at once); warm
  // ~20s, cold blows past Playwright's 30s default. These budgets cover the cold case.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: WEB_BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
