import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { API_BASE_URL } from "../harness";

const NOISE = [
  "posthog",
  "PostHog",
  "localhost:4747",
  "favicon",
  "Download the React DevTools",
  "Fast Refresh",
  "Failed to load resource",
  "net::ERR_",
];

const isNoise = (text: string) => NOISE.some((needle) => text.includes(needle));

/**
 * The Effect UI Todos list must look and behave like the React route. The
 * pixel diff lives in scripts/effect-ui/visual-parity.mjs; this spec proves
 * the interaction and the accessible surface on a todo it owns, so it never
 * races the shared seed fixture.
 */
test.describe("Effect UI todos", () => {
  test("toggles a todo and persists it", async ({ page }) => {
    const title = `Effect UI toggle ${Date.now()}`;
    const created = await page.request.post(`${API_BASE_URL}/todos`, {
      data: { title },
    });
    expect(created.ok()).toBeTruthy();
    const todo = (await created.json()) as { id: string };

    try {
      const consoleErrors: string[] = [];
      const failedApi: string[] = [];
      page.on("pageerror", (error) => consoleErrors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error" && !isNoise(message.text())) {
          consoleErrors.push(message.text());
        }
      });
      page.on("response", (response) => {
        if (
          response.url().includes("/api/v1/todos") &&
          response.status() >= 400
        ) {
          failedApi.push(`${response.status()} ${response.url()}`);
        }
      });

      await page.goto("/todos?effect=1");

      const row = page.locator("[data-index]").filter({ hasText: title });
      await expect(row).toBeVisible();

      const checkbox = page.getByRole("checkbox", {
        name: `Toggle ${title}`,
      });
      await checkbox.check();

      // The default list is `completed=false`, so a completed task leaves it.
      await expect(
        page.locator("[data-index]").filter({ hasText: title }),
      ).toHaveCount(0);

      await page.reload();
      await expect(
        page.locator("[data-index]").filter({ hasText: title }),
      ).toHaveCount(0);

      expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
      expect(failedApi, failedApi.join("\n")).toEqual([]);

      const accessibility = await new AxeBuilder({ page })
        .include("[data-effect-ui-root]")
        .analyze();
      expect(accessibility.violations).toEqual([]);
    } finally {
      await page.request.delete(`${API_BASE_URL}/todos/${todo.id}`);
    }
  });
});
