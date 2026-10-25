import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the self-host end-to-end journey, run by the
 * selfhost-e2e lane against a stack `gaia up` booted on the runner (see
 * scripts/ci/selfhost.sh). One stateful journey, so one worker in file order.
 * Every test keeps its trace and screenshots: the lane uploads them.
 */
export default defineConfig({
  testDir: "./e2e/selfhost",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  timeout: 300_000,
  expect: { timeout: 60_000 },
  outputDir: "test-results/selfhost",
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report/selfhost" }],
  ],
  use: {
    baseURL: process.env.SELFHOST_URL ?? "http://localhost:3000",
    trace: "on",
    screenshot: "on",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
