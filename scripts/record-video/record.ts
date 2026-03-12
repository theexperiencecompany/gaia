import { chromium } from "playwright";
import { mkdirSync, renameSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { convertWebmToMp4, type Quality } from "./convert.js";

export type Format = "9:16" | "16:9";

const VIEWPORTS: Record<Format, { width: number; height: number }> = {
  "9:16": { width: 390, height: 844 },
  "16:9": { width: 1920, height: 1080 },
};

export interface RecordOptions {
  scenarioId: string;
  format?: Format;
  outputPath?: string;
  devServerUrl?: string;
  quality?: Quality;
  timeoutMs?: number;
}

export async function recordScenario(options: RecordOptions): Promise<string> {
  const {
    scenarioId,
    format = "9:16",
    outputPath,
    devServerUrl = "http://localhost:3000",
    quality = "high",
    timeoutMs = 5 * 60 * 1000,
  } = options;

  const viewport = VIEWPORTS[format];
  const formatSlug = format.replace(":", "x");
  const finalOutput =
    outputPath ?? `output/videos/${scenarioId}-${formatSlug}.mp4`;

  mkdirSync(dirname(finalOutput), { recursive: true });

  const tmpDir = join(tmpdir(), `gaia-recording-${Date.now()}`);
  mkdirSync(tmpDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });

  const context = await browser.newContext({
    viewport,
    recordVideo: { dir: tmpDir, size: viewport },
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  });

  const page = await context.newPage();
  // Disable default page timeout so explicit per-call timeouts are respected
  page.setDefaultTimeout(0);
  const url = `${devServerUrl}/record/${scenarioId}`;

  console.log(`\nRecording: ${url}`);
  console.log(`Viewport: ${viewport.width}×${viewport.height} (${format})`);

  await page.goto(url, { waitUntil: "domcontentloaded" });

  // Wait for any recording state — with server-side preloading the page may
  // transition from "idle" to "started" before we first poll, so accept either.
  await page.waitForFunction(
    () => document.title.startsWith("recording:"),
    { timeout: 30_000 },
  );
  console.log("✓ Scenario loaded");

  // If already started (idle was missed), that's fine — just proceed.
  await page.waitForFunction(
    () =>
      document.title === "recording:started" ||
      document.title === "recording:done",
    { timeout: 15_000 },
  );
  console.log("✓ Recording started");

  await page.waitForFunction(() => document.title === "recording:done", {
    timeout: timeoutMs,
  });
  console.log("✓ Scenario complete");

  await page.waitForTimeout(500);

  await context.close();
  await browser.close();

  const { readdirSync } = await import("node:fs");
  const files = readdirSync(tmpDir).filter((f) => f.endsWith(".webm"));
  if (files.length === 0) {
    throw new Error("No WebM file found in recording temp directory");
  }

  const webmPath = join(tmpDir, files[0]);
  console.log(`✓ WebM recorded: ${webmPath}`);

  await convertWebmToMp4(webmPath, finalOutput, quality);

  return finalOutput;
}
