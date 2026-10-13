import { expect, type Page, test } from "@playwright/test";
import { collectSurfaces, type SurfaceGroup } from "./surfaces";

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
  test(`${surface.group} ${surface.path}`, async ({ page }) => {
    // Live third-party data (GitHub stars, status feeds) differs between runs; force the fallback.
    await page.route(
      (url) => url.hostname !== "localhost",
      (route) =>
        LIVE_DATA_TYPES.has(route.request().resourceType())
          ? route.abort()
          : route.continue(),
    );
    await page.clock.setFixedTime(FROZEN_NOW);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize(VIEWPORTS[surface.group]);

    const response = await page.goto(surface.path);
    expect(response?.status(), `${surface.path} did not render`).toBeLessThan(
      400,
    );
    await settle(page);

    await expect(page).toHaveScreenshot(`${surface.id}.png`, {
      fullPage: FULL_PAGE[surface.group],
      animations: "disabled",
      caret: "hide",
    });
  });
}
