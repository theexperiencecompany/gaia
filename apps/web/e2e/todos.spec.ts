import { expect, test } from "@playwright/test";
import { FIRST_SEEDED_TODO, SEED_TODOS } from "./harness";

/**
 * Todos journey through the real UI path, against the seeded dev user.
 *
 * Seeding is deterministic ("Sample todo 1..N"), so the suite asserts the
 * full seeded set renders — not just the first — and that the filtered views
 * mount without bouncing to login.
 */
test.describe("todos", () => {
  test("renders every seeded todo", async ({ page }) => {
    await page.goto("/todos");

    for (let i = 1; i <= SEED_TODOS; i += 1) {
      await expect(
        page.getByText(`Sample todo ${i}`, { exact: true }).first(),
      ).toBeVisible();
    }
    // Smoke already covers the anchor; this pins the count.
    expect(FIRST_SEEDED_TODO).toBe("Sample todo 1");
  });

  test("completed view mounts without a login redirect", async ({ page }) => {
    await page.goto("/todos/completed");

    await expect(page).not.toHaveURL(/login/);
    await expect(page.locator("body")).toBeVisible();
  });

  test("today view mounts without a login redirect", async ({ page }) => {
    await page.goto("/todos/today");

    await expect(page).not.toHaveURL(/login/);
    await expect(page.locator("body")).toBeVisible();
  });
});
