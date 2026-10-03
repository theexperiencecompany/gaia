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
      await page.goto(route);

      await expect(page).not.toHaveURL(/login/);
      await expect(page).not.toHaveURL(/onboarding/);
      await expect(page.locator("body")).toBeVisible();
    });
  }
});
