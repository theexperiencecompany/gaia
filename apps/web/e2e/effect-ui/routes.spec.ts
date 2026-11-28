import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * Per-page coverage for the Effect UI migration. The route list is generated
 * from the App Router by scripts/effect-ui/generate-route-manifest.mjs, so a
 * new page is covered by rerunning the generator, not by editing this file.
 */
interface ManifestRoute {
  readonly path: string;
  readonly file: string;
  readonly ported: boolean;
  readonly skip: boolean;
  readonly reason: string | null;
}

const MANIFEST: readonly ManifestRoute[] = JSON.parse(
  readFileSync(new URL("./routes.generated.json", import.meta.url), "utf8"),
);

/** Same shell set as e2e/app-shell.spec.ts; these run ported or not. */
const APP_SHELL_ROUTES = new Set([
  "/c",
  "/todos",
  "/calendar",
  "/workflows",
  "/integrations",
  "/settings",
  "/notifications",
]);

/**
 * Default run covers ported routes plus the app shell. E2E_EFFECT_ALL=1 widens
 * it to every non-skipped route. One test per route, no shared state, so
 * fullyParallel keeps working.
 */
const RUN_ALL = process.env.E2E_EFFECT_ALL === "1";
const ROUTES = MANIFEST.filter(
  (route) =>
    !route.skip &&
    (RUN_ALL || route.ported || APP_SHELL_ROUTES.has(route.path)),
);

/** A dev server pays a Turbopack compile on the first visit to a route. */
const NAVIGATION_TIMEOUT_MS = 90_000;

/**
 * Uncaught errors that are not the page's fault: analytics blocked in dev, the
 * browser's benign ResizeObserver loop warning, fetch aborts on route change,
 * and Turbopack hot-reload chunk noise. Anything else fails the route.
 */
const PAGE_ERROR_NOISE = [
  /posthog/i,
  /ResizeObserver loop/i,
  /^(AbortError|The user aborted a request)/i,
  /^(Failed to fetch|Load failed|NetworkError)/i,
  /ChunkLoadError|Loading chunk .* failed/i,
  /NEXT_REDIRECT/,
];

test.describe("effect ui route coverage", () => {
  for (const route of ROUTES) {
    const label = route.ported ? `${route.path} (effect)` : route.path;

    test(`${label} renders`, async ({ page }, testInfo) => {
      const pageErrors: string[] = [];
      page.on("pageerror", (error) => {
        if (!PAGE_ERROR_NOISE.some((pattern) => pattern.test(error.message))) {
          pageErrors.push(error.message);
        }
      });

      const target = route.ported ? `${route.path}?effect=1` : route.path;
      const response = await page.goto(target, {
        waitUntil: "domcontentloaded",
        timeout: NAVIGATION_TIMEOUT_MS,
      });

      if (!response) {
        throw new Error(`${target} returned no document response`);
      }
      expect(response.status(), `${target} HTTP status`).toBeLessThan(400);
      await expect(page.locator("body")).toBeVisible();

      // A blank body or an error boundary renders neither.
      await expect(page.locator("main, [role=main], h1").first()).toBeVisible();

      await page.screenshot({ path: testInfo.outputPath("page.png") });

      if (route.ported) {
        const root = page.locator("[data-effect-ui-root]");
        await expect(root).toBeVisible();
        // The host div exists before Effect mounts into it, and the page's own
        // "Loading …" placeholder is transient. Scanning either would pass on
        // an empty node or flag text the user never gets to read.
        await expect(root).not.toBeEmpty({ timeout: 30_000 });
        await expect(root).not.toContainText(/Loading/i, { timeout: 30_000 });

        const accessibility = await new AxeBuilder({ page })
          .include("[data-effect-ui-root]")
          .analyze();
        // Color contrast is a pre-existing GAIA baseline: the React routes use
        // the same zinc-on-#111 text. Track it separately instead of letting it
        // hide a new structural violation in the port.
        const unexpected = accessibility.violations.filter(
          (violation) => violation.id !== "color-contrast",
        );
        expect(
          unexpected,
          unexpected
            .map((violation) => `${violation.id}: ${violation.help}`)
            .join("\n"),
        ).toEqual([]);
      }

      expect(pageErrors, pageErrors.join("\n")).toEqual([]);
    });
  }
});
