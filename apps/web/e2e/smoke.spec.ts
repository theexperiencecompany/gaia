import { expect, test } from "@playwright/test";
import {
  FIRST_SEEDED_TODO,
  SCRIPTED_CHAT_MESSAGE,
  SCRIPTED_REPLY,
  SIM_ENABLED,
} from "./harness";

const COMPOSER_PLACEHOLDER = "What can I do for you today?";

/**
 * Smoke template for GAIA web e2e. Rides the dev harness — no login, no manual
 * data. `global-setup` seeds the authenticated user before these run.
 */
test.describe("smoke", () => {
  test("loads the authenticated app without a login redirect", async ({
    page,
  }) => {
    await page.goto("/c");

    // The composer only renders inside the authenticated app shell. Its
    // presence proves the dev bypass authenticated us and the onboarding guard
    // did not bounce us to /onboarding.
    await expect(
      page.getByPlaceholder(COMPOSER_PLACEHOLDER, { exact: false }),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/c(\/|$|\?)/);
  });

  test("shows the seeded todos", async ({ page }) => {
    await page.goto("/todos");

    // Seeding may run repeatedly across runs, so the title can appear more than
    // once — assert at least the first is reachable.
    await expect(
      page.getByText(FIRST_SEEDED_TODO, { exact: true }).first(),
    ).toBeVisible();
  });

  test("renders the scripted chat reply", async ({ page }) => {
    test.skip(
      !SIM_ENABLED,
      "Requires the deterministic sim stack. Run `mise dev:sim` and set E2E_SIM=1.",
    );

    await page.goto("/c");

    const composer = page.getByPlaceholder(COMPOSER_PLACEHOLDER, {
      exact: false,
    });
    await expect(composer).toBeVisible();

    await composer.fill(SCRIPTED_CHAT_MESSAGE);
    await composer.press("Enter");

    // The stub turns `[[say:Done!]]` into an assistant reply of exactly "Done!"
    // through the real agent graph. Exact match avoids matching the echoed
    // user directive "[[say:Done!]]".
    await expect(
      page.getByText(SCRIPTED_REPLY, { exact: true }).first(),
    ).toBeVisible();
  });
});
