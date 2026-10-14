import { expect, test } from "@playwright/test";

/**
 * App shell coverage: every main route must render for the seeded,
 * onboarding-complete dev user instead of bouncing to login or onboarding.
 *
 * Smoke only visits /c and /todos, so a guard regression on any other route
 * (paywall modal loop, onboarding bounce, auth redirect) is invisible until
 * a user hits it. These pin the shell on each route without asserting page
 * content — content belongs to per-feature specs.
 */
const MAIN_ROUTES = [
  "/c",
  "/todos",
  "/calendar",
  "/workflows",
  "/integrations",
  "/settings",
  "/notifications",
] as const;

test.describe("app shell", () => {
  for (const route of MAIN_ROUTES) {
    test(`${route} renders inside the authenticated shell`, async ({
      page,
    }) => {
      const response = await page.goto(route);

      // HTTP-level proof: no 404/500 page can pass, regardless of content.
      expect(response?.status(), `${route} HTTP status`).toBeLessThan(400);
      // toHaveURL retries: a delayed client-side redirect to login or
      // onboarding fails this instead of slipping past an immediate check.
      await expect(page).toHaveURL(new RegExp(`${route}(\\?|#|$|/)`));
      await expect(page.locator("body")).toBeVisible();
    });
  }
});
