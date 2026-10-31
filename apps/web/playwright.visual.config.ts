import { defineConfig, devices } from "@playwright/test";

/**
 * Screenshot diff of the key marketing pages on the built Cloudflare worker,
 * run through `scripts/ci/smoke-worker.sh visual`. The baseline is captured on
 * the base branch's build (`visual update`) and every later build must match it
 * pixel for pixel: no colour threshold, no tolerated pixel count.
 */
const baseURL = process.env.SMOKE_BASE_URL;
if (!baseURL) {
  throw new Error(
    "SMOKE_BASE_URL is unset: run this through scripts/ci/smoke-worker.sh visual",
  );
}

export default defineConfig({
  testDir: "./e2e/visual",
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 2,
  timeout: 180_000,
  expect: {
    timeout: 60_000,
    toHaveScreenshot: {
      threshold: 0,
      maxDiffPixels: 0,
      animations: "disabled",
      caret: "hide",
      scale: "device",
    },
  },
  outputDir: "test-results/visual",
  snapshotPathTemplate: "{testDir}/.baseline/{projectName}/{arg}{ext}",
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "off",
    locale: "en-US",
    timezoneId: "UTC",
    contextOptions: { reducedMotion: "reduce" },
    colorScheme: "dark",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome",
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
      },
    },
    {
      name: "mobile",
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome",
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
