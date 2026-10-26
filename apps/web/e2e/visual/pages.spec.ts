import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, type Page, type Route, test } from "@playwright/test";

/**
 * Every key marketing page must render pixel-identical to the baseline build.
 * Third-party responses (API, CDN logos, avatars) are recorded beside the
 * baseline and replayed afterwards, so both builds see the same bytes.
 */
const PAGES = [
  "/",
  "/pricing",
  "/about",
  "/contact",
  "/features",
  "/compare",
  "/compare/motion",
  "/alternative-to/motion",
  "/for/consultants",
  "/de/for/consultants",
  "/learn/agent-loop",
  "/automate",
  "/automate/airtable-notion",
  "/blog",
  "/blog/desktop",
  "/faq",
  "/marketplace",
  "/marketplace/airtable",
  "/use-cases/morning-briefing",
  "/bots",
];

const FIXED_TIME = new Date("2026-01-15T12:00:00Z");
const CF_IMAGE_PREFIX = "/cdn-cgi/image/";
const UPDATING = process.env.VISUAL_UPDATE === "1";
const SCROLL_SETTLE_MS = 150;
// The page clock only moves when told to, so every run sees the same animation frame.
const SCROLL_CLOCK_STEP_MS = 1_000;
const FINAL_CLOCK_STEP_MS = 60_000;
// local workerd drops the odd connection under two parallel browsers
const NETWORK_RETRIES = 2;
const THIRD_PARTY_TIMEOUT_MS = 15_000;
const IMAGE_TIMEOUT_MS = 30_000;

function snapshotName(route: string): string {
  return route === "/" ? "home" : route.slice(1).replaceAll("/", "__");
}

interface RecordedResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
}

/** null: the request failed on the baseline run, so the replay fails it too. */
type Recording = Record<string, RecordedResponse | null>;

function requestKey(route: Route): string {
  const request = route.request();
  return `${request.method()} ${request.url()}`;
}

async function recordResponse(route: Route): Promise<RecordedResponse | null> {
  try {
    const response = await route.fetch({
      maxRetries: NETWORK_RETRIES,
      timeout: THIRD_PARTY_TIMEOUT_MS,
    });
    return {
      status: response.status(),
      headers: response.headers(),
      body: (await response.body()).toString("base64"),
    };
  } catch (error) {
    // A third party that is down during the baseline is part of what the baseline saw.
    console.warn(`baseline: ${route.request().url()} failed: ${error}`);
    return null;
  }
}

/**
 * Off-origin requests are fetched from Node on the baseline run (the API's CORS
 * names heygaia.io, not the local worker) and served from the recording after;
 * a request the baseline never made is aborted.
 */
async function replayThirdParty(
  page: Page,
  origin: string,
  recordingPath: string,
): Promise<() => void> {
  const recording: Recording =
    !UPDATING && existsSync(recordingPath)
      ? JSON.parse(readFileSync(recordingPath, "utf8"))
      : {};
  await page.route(
    (url) => url.origin !== origin,
    async (route) => {
      const key = requestKey(route);
      if (UPDATING && !(key in recording)) {
        recording[key] = await recordResponse(route);
      }
      const recorded = recording[key];
      if (!recorded) {
        await route.abort();
        return;
      }
      await route.fulfill({
        status: recorded.status,
        headers: {
          ...recorded.headers,
          "access-control-allow-origin": origin,
          "access-control-allow-credentials": "true",
        },
        body: Buffer.from(recorded.body, "base64"),
      });
    },
  );
  return () => {
    if (!UPDATING) return;
    mkdirSync(path.dirname(recordingPath), { recursive: true });
    writeFileSync(recordingPath, JSON.stringify(recording));
  };
}

/** Cloudflare resizes /cdn-cgi/image/<options>/<path> at the edge; locally the original is served. */
async function serveImagesUnresized(page: Page, origin: string): Promise<void> {
  await page.route(
    (url) => url.origin === origin && url.pathname.startsWith(CF_IMAGE_PREFIX),
    async (route) => {
      const { pathname } = new URL(route.request().url());
      const source = pathname
        .slice(CF_IMAGE_PREFIX.length)
        .replace(/^[^/]+\//, "/");
      const response = await route.fetch({
        url: `${origin}${source}`,
        maxRetries: NETWORK_RETRIES,
      });
      await route.fulfill({ response });
    },
  );
}

/** Scroll the whole page so lazy images and in-view reveals load, then run every animation to its end at the top. */
async function settle(page: Page): Promise<void> {
  const step = page.viewportSize()?.height ?? 800;
  for (
    let y = 0;
    y < (await page.evaluate(() => document.documentElement.scrollHeight));
    y += step
  ) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(SCROLL_SETTLE_MS);
    await page.clock.runFor(SCROLL_CLOCK_STEP_MS);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  // Twice: an image that lands schedules timers (fades, progressive swaps), and those timers can load more.
  for (let pass = 0; pass < 2; pass++) {
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready);
    await waitForStartedImages(page);
    await page.clock.runFor(FINAL_CLOCK_STEP_MS);
  }
}

/** Every image the browser has begun fetching has landed; lazy images never scrolled near stay unstarted. */
async function waitForStartedImages(page: Page): Promise<void> {
  const pending = () =>
    Array.from(document.images)
      .filter((image) => !image.complete && image.currentSrc !== "")
      .map((image) => image.currentSrc);
  try {
    await page.waitForFunction(
      () =>
        Array.from(document.images).every(
          (image) => image.complete || image.currentSrc === "",
        ),
      undefined,
      { polling: 250, timeout: IMAGE_TIMEOUT_MS },
    );
  } catch {
    throw new Error(
      `images still loading: ${(await page.evaluate(pending)).join(", ")}`,
    );
  }
}

/** A fixed-seed Math.random, so anything laid out from random numbers lands the same way each run. */
function seedRandom(): void {
  let state = 0x9e3779b9;
  Math.random = () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

for (const route of PAGES) {
  test(route, async ({ page, baseURL }) => {
    if (!baseURL) throw new Error("run through playwright.visual.config.ts");
    const origin = new URL(baseURL).origin;
    const name = snapshotName(route);
    const saveRecording = await replayThirdParty(
      page,
      origin,
      test.info().snapshotPath(`${name}.responses.json`),
    );
    await serveImagesUnresized(page, origin);
    await page.clock.install({ time: FIXED_TIME });
    await page.clock.pauseAt(FIXED_TIME);
    await page.addInitScript(seedRandom);

    await page.goto(route, { waitUntil: "load" });
    await settle(page);

    saveRecording();

    // The footer wordmark canvas ripples toward the pointer, which scrolling moves across it.
    await expect(page).toHaveScreenshot(`${name}.png`, {
      fullPage: true,
      mask: [page.locator("canvas")],
    });
  });
}
