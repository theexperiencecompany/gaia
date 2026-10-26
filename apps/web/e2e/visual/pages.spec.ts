import { expect, type Page, test } from "@playwright/test";

/**
 * Every key marketing page must render pixel-identical to the baseline build.
 * Third-party responses (API, CDN logos, avatars) are recorded into a HAR on
 * the baseline run and replayed afterwards, so both builds see the same bytes.
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

/** Every URL not on the worker under test: routeFromHAR matches only a string or RegExp. */
function offOrigin(origin: string): RegExp {
  return new RegExp(`^(?!${origin.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/)`);
}

function snapshotName(route: string): string {
  return route === "/" ? "home" : route.slice(1).replaceAll("/", "__");
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
      const response = await route.fetch({ url: `${origin}${source}` });
      await route.fulfill({ response });
    },
  );
}

/** Scroll the whole page so lazy images and in-view reveals load, then return to the top. */
async function settle(page: Page): Promise<void> {
  const height = await page.evaluate(
    () => document.documentElement.scrollHeight,
  );
  const step = page.viewportSize()?.height ?? 800;
  for (let y = 0; y < height; y += step) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(SCROLL_SETTLE_MS);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForLoadState("networkidle");
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      Array.from(document.images, (image) =>
        image.complete ? undefined : image.decode().catch(() => undefined),
      ),
    );
  });
}

for (const route of PAGES) {
  test(route, async ({ page, context, baseURL }) => {
    if (!baseURL) throw new Error("run through playwright.visual.config.ts");
    const origin = new URL(baseURL).origin;
    const name = snapshotName(route);
    const har = test.info().snapshotPath(`${name}.har`);

    await context.routeFromHAR(har, {
      url: offOrigin(origin),
      update: UPDATING,
      updateContent: "embed",
      notFound: "abort",
    });
    await serveImagesUnresized(page, origin);
    await page.clock.install({ time: FIXED_TIME });

    await page.goto(route, { waitUntil: "load" });
    await settle(page);

    await expect(page).toHaveScreenshot(`${name}.png`, { fullPage: true });
  });
}
