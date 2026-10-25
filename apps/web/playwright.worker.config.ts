import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the built Cloudflare worker that
 * `scripts/ci/smoke-worker.sh` boots in workerd. It needs no API or seeded
 * user, and drives the runner's own Chrome so CI downloads no browser.
 */
const baseURL = process.env.SMOKE_BASE_URL;
if (!baseURL) {
  throw new Error(
    "SMOKE_BASE_URL is unset: run this through scripts/ci/smoke-worker.sh",
  );
}

export default defineConfig({
  testDir: "./e2e/worker",
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "off",
  },
  projects: [
    {
      name: "chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});
