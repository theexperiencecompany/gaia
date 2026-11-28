import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { FIRST_SEEDED_TODO } from "../harness";

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
 * the interaction and the accessible surface.
 */
test.describe("Effect UI todos", () => {
  test("toggles a seeded todo and persists it", async ({ page }) => {
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

    const open = page.getByRole("button", {
      name: `Open todo ${FIRST_SEEDED_TODO}`,
    });
    await expect(open).toBeVisible();

    const checkbox = page.getByRole("checkbox", {
      name: `Toggle ${FIRST_SEEDED_TODO}`,
    });
    await checkbox.check();

    // The default list is `completed=false`, so a completed task leaves it.
    await expect(
      page.getByRole("button", { name: `Open todo ${FIRST_SEEDED_TODO}` }),
    ).toHaveCount(0);

    await page.reload();
    await expect(
      page.getByRole("button", { name: `Open todo ${FIRST_SEEDED_TODO}` }),
    ).toHaveCount(0);

    expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
    expect(failedApi, failedApi.join("\n")).toEqual([]);

    const accessibility = await new AxeBuilder({ page })
      .include("[data-effect-ui-root]")
      .analyze();
    expect(accessibility.violations).toEqual([]);
  });
});
