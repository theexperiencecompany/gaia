import { defineConfig, devices } from "@playwright/test";

/**
 * Visual diff of base vs head (`mise web:visual-diff`). The orchestrator runs
 * this twice against two dev servers: once with --update-snapshots=all to
 * record base, then plain to compare head; every mismatch keeps the
 * expected/actual/diff triple for the report.
 */
const OUT_DIR = process.env.VISUAL_OUT;
const BASE_URL = process.env.VISUAL_BASE_URL;
if (!OUT_DIR || !BASE_URL) {
  throw new Error(
    "VISUAL_OUT and VISUAL_BASE_URL are required — run through `mise web:visual-diff`",
  );
}

// VISUAL_GREP narrows a run to some surfaces, e.g. '\bapp /' for the signed-in routes only.
const GREP = process.env.VISUAL_GREP;

export default defineConfig({
  testDir: "./e2e/visual",
  grep: GREP ? new RegExp(GREP) : undefined,
  snapshotPathTemplate: `${OUT_DIR}/baseline/{arg}{ext}`,
  outputDir: `${OUT_DIR}/results`,
  fullyParallel: true,
  retries: 0,
  // One page at a time: the dev server already saturates the CPU compiling routes.
  workers: 1,
  // Dev servers compile each route on first visit; cold Turbopack compiles exceed the 30s default.
  timeout: 180_000,
  expect: {
    timeout: 30_000,
    toHaveScreenshot: {
      maxDiffPixels: 0,
      stylePath: "./e2e/visual/screenshot.css",
    },
  },
  reporter: [
    ["list"],
    ["json", { outputFile: `${OUT_DIR}/results.json` }],
    ["html", { open: "never", outputFolder: `${OUT_DIR}/report` }],
  ],
  use: {
    baseURL: BASE_URL,
    ...devices["Desktop Chrome"],
    deviceScaleFactor: 1,
  },
});
