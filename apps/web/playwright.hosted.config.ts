import { defineConfig, devices } from "@playwright/test";

/**
 * Hosted (non-self-hosted) e2e lane. Every backend call is mocked at the
 * browser boundary, so it needs only the Next dev server: no API, database,
 * containers or secrets. Run it with `pnpm test:e2e:hosted`.
 */
const WEB_PORT = process.env.HOSTED_E2E_PORT ?? "3457";
const WEB_ORIGIN = `http://localhost:${WEB_PORT}`;
const BASE_URL = process.env.HOSTED_E2E_BASE_URL ?? WEB_ORIGIN;

export default defineConfig({
  testDir: "./e2e/hosted",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  // Cold Turbopack compiles dominate the first run; warm, the journey is <30s.
  timeout: 120_000,
  expect: { timeout: 10_000 },
  outputDir: "test-results/hosted",
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    // The onboarding wizard and receipt printer both collapse their timers
    // under reduced motion; the assertions themselves never wait on animation.
    contextOptions: { reducedMotion: "reduce" },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: process.env.HOSTED_E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm exec next dev --turbopack --port=${WEB_PORT}`,
        url: WEB_ORIGIN,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          // A loopback origin distinct from the web app, so `/login`'s OAuth
          // handoff is a real document navigation (and mockable) even when mise
          // does not export its own `localhost:8000` default.
          NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000/api/v1",
          NEXT_PUBLIC_DODO_MODE: "test",
          NEXT_TELEMETRY_DISABLED: "1",
        },
      },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
