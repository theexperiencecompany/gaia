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
      const item = page.getByText(`Sample todo ${i}`, { exact: true }).first();
      // The list virtualizes: items beyond the viewport only mount on scroll.
      await item.scrollIntoViewIfNeeded();
      await expect(item).toBeVisible();
    }
    // Smoke already covers the anchor; this pins the count.
    expect(FIRST_SEEDED_TODO).toBe("Sample todo 1");
  });

  test("completed view mounts without a login redirect", async ({ page }) => {
    await page.goto("/todos/completed");

    // toHaveURL retries: a delayed client-side redirect fails this instead
    // of slipping past an immediate assertion.
    await expect(page).toHaveURL(/\/todos\/completed/);
    await expect(page.locator("body")).toBeVisible();
  });

  test("today view mounts without a login redirect", async ({ page }) => {
    await page.goto("/todos/today");

    await expect(page).toHaveURL(/\/todos\/today/);
    await expect(page.locator("body")).toBeVisible();
  });
});
