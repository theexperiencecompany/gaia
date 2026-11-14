import { defineConfig, devices } from "@playwright/test";

/**
 * Computed-style parity of every HeroUI primitive GAIA renders against v2's
 * values (e2e/primitive-parity/v2-snapshot.json), read off the dev-only
 * fixture at /dev/primitive-parity. Run through `mise web:primitive-parity`;
 * PARITY_BASE_URL points it at a server already running the fixture, otherwise
 * it starts `next dev`.
 */
const PORT = 3217;
const baseURL = process.env.PARITY_BASE_URL ?? `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e/primitive-parity",
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  outputDir: "test-results/primitive-parity/output",
  reporter: [["list"]],
  webServer: process.env.PARITY_BASE_URL
    ? undefined
    : {
        command: `pnpm exec next dev --port ${PORT}`,
        url: `${baseURL}/dev/primitive-parity`,
        reuseExistingServer: true,
        timeout: 300_000,
      },
  use: {
    baseURL,
    trace: "off",
    actionTimeout: 15_000,
    locale: "en-US",
    timezoneId: "UTC",
    colorScheme: "dark",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome",
        viewport: { width: 1440, height: 1000 },
        deviceScaleFactor: 1,
      },
    },
  ],
});
