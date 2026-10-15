import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { captureDom } from "./dom";
import { collectSurfaces, type SurfaceGroup } from "./surfaces";
import type { Side } from "./types";

const SIDES: readonly Side[] = ["base", "head"];
const SIDE = SIDES.find((side) => side === process.env.VISUAL_SIDE);
const OUT_DIR = process.env.VISUAL_OUT;
if (!SIDE || !OUT_DIR) {
  throw new Error(
    "VISUAL_SIDE (base or head) and VISUAL_OUT are required — run through `mise web:visual-diff`",
  );
}
const DOM_DIR = join(OUT_DIR, "dom");
// The screenshot hides these via stylePath; apply them before the DOM snapshot too.
const SCREENSHOT_CSS = join(import.meta.dirname, "screenshot.css");

// Pinned so relative times ("2 hours ago") and date pickers render identically on both runs.
const FROZEN_NOW = new Date("2026-01-15T10:00:00Z");
const SCROLL_STEP_PX = 800;
const LIVE_DATA_TYPES = new Set(["fetch", "xhr"]);

// Tool cards and OpenUI render inside an h-screen scroll container, so they get a tall viewport.
const VIEWPORTS: Record<SurfaceGroup, { width: number; height: number }> = {
  "tool-card": { width: 1280, height: 2400 },
  openui: { width: 1280, height: 2400 },
  landing: { width: 1440, height: 900 },
  app: { width: 1440, height: 900 },
};

const FULL_PAGE: Record<SurfaceGroup, boolean> = {
  "tool-card": false,
  openui: false,
  landing: true,
  app: false,
};

/** Walk the page once so lazy images load and in-view reveals fire before capture. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await page.evaluate(async (step) => {
    const pause = () => new Promise((resolve) => setTimeout(resolve, 120));
    for (let y = 0; y < document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await pause();
    }
    window.scrollTo(0, 0);
    await document.fonts.ready;
  }, SCROLL_STEP_PX);
  await page.waitForLoadState("networkidle");
}

for (const surface of collectSurfaces(process.env.VISUAL_APP === "1")) {
  const title = `${surface.group} ${surface.path}`;
  test(title, async ({ page }) => {
    // Off-site: a page navigation means the route redirects away (not our UI);
    // live data (GitHub stars, status feeds) differs between runs, so force the fallback.
    let leftSite = false;
    await page.route(
      (url) => url.hostname !== "localhost",
      (route) => {
        const request = route.request();
        if (
          request.isNavigationRequest() &&
          request.frame() === page.mainFrame()
        ) {
          leftSite = true;
          return route.abort();
        }
        return LIVE_DATA_TYPES.has(request.resourceType())
          ? route.abort()
          : route.continue();
      },
    );
    await page.clock.setFixedTime(FROZEN_NOW);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize(VIEWPORTS[surface.group]);

    const response = await page.goto(surface.path).catch((error: Error) => {
      if (leftSite) return null;
      throw error;
    });
    test.skip(leftSite, `${surface.path} redirects off-site`);
    expect(response?.status(), `${surface.path} did not render`).toBeLessThan(
      400,
    );
    await settle(page);

    await page.addStyleTag({ path: SCREENSHOT_CSS });
    // Settle animations the way the screenshot's animations: "disabled" does, so the
    // DOM snapshot never records a mid-frame value: finite ones end, infinite ones reset.
    await page.evaluate(() => {
      for (const animation of document.getAnimations()) {
        if (animation.effect?.getComputedTiming().endTime === Infinity)
          animation.cancel();
        else animation.finish();
      }
    });
    const snapshot = await captureDom(page, {
      id: surface.id,
      title,
      side: SIDE,
    });
    mkdirSync(DOM_DIR, { recursive: true });
    writeFileSync(
      join(DOM_DIR, `${surface.id}.${SIDE}.json`),
      JSON.stringify(snapshot),
    );

    await expect(page).toHaveScreenshot(`${surface.id}.png`, {
      fullPage: FULL_PAGE[surface.group],
      animations: "disabled",
      caret: "hide",
    });
  });
}
