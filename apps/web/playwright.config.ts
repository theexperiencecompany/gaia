import { defineConfig, devices } from "@playwright/test";
import { WEB_BASE_URL } from "./e2e/harness";

/**
 * Playwright config for GAIA web e2e.
 *
 * Runs against an already-running dev stack (`mise dev --sim`, or `mise dev --agent`
 * for a real LLM — both boot with the dev auth bypass on). There is no auth
 * fixture because the dev bypass
 * authenticates every page load. `global-setup` mints + seeds the dev user, so
 * specs start from deterministic data. Ports come from `WEB_PORT` / `API_PORT`
 * so per-worktree ports work unchanged.
 */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 1 : undefined,
  // The target is always a Next.js DEV server, so the first visit to a route
  // pays a Turbopack compile — and with fullyParallel every worker pays it at
  // once. Measured warm, a spec takes ~20s; cold it blows past Playwright's 30s
  // default and fails on a skeleton loader. These budgets cover the cold case;
  // a warm run still finishes in ~25s because nothing waits out its timeout.
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
