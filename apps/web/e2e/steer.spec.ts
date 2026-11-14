import { expect, test } from "@playwright/test";
import { COMPOSER_PLACEHOLDER, SIM_ENABLED } from "./harness";

/** Enough scripted tool calls to hold turn 1's stream open for seconds. */
const LONG_TASK = `stock the pantry ${Array.from(
  { length: 12 },
  (_, i) => `[[tool:create_todo {"title":"pantry-${i}"}]]`,
).join(" ")} [[say:Pantry stocked.]]`;

const STEER_MESSAGE = "also add oat milk [[say:Steered in.]]";

/**
 * Mid-turn steering through the real UI path, against the sim stack only
 * (no model cost, fully deterministic).
 *
 * The second message must be sent before the first one's answer lands:
 * nothing holds a send behind a running reply. The server folds it into the
 * conversation.
 */
test.describe("steer", () => {
  test("a mid-turn send posts while the first turn still streams", async ({
    page,
  }) => {
    test.skip(
      !SIM_ENABLED,
      "Requires the deterministic sim stack. Run `mise dev --sim` and set E2E_SIM=1.",
    );

    await page.goto("/c");
    const composer = page.getByPlaceholder(COMPOSER_PLACEHOLDER, {
      exact: false,
    });
    await expect(composer).toBeVisible();

    const started = new Map<string, number>();
    page.on("request", (request) => {
      if (
        !/\/conversations\/[^/]+\/messages$/.test(
          new URL(request.url()).pathname,
        ) ||
        request.method() !== "POST"
      )
        return;
      const body = JSON.parse(request.postData() ?? "{}") as {
        message_id?: string;
      };
      if (body.message_id) started.set(body.message_id, Date.now());
    });

    await composer.fill(LONG_TASK);
    await composer.press("Enter");

    // Wait until turn 1 truly streams mid-run: the route bind plus a mid-list
    // tool card prove the tool loop is underway, not just the echoed bubble.
    await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}/, { timeout: 60_000 });
    await expect(page.getByText("pantry-6").first()).toBeVisible({
      timeout: 60_000,
    });

    await composer.fill(STEER_MESSAGE);
    await composer.press("Enter");

    await expect
      .poll(() => started.size, { timeout: 30_000 })
      .toBeGreaterThanOrEqual(2);
    expect(
      await page.getByText("Pantry stocked.").count(),
      "the second message is sent while the first is still being answered",
    ).toBe(0);

    const [first, second] = [...started.keys()];
    expect(second, "the second send is its own message").not.toBe(first);

    // Both answers render in the same conversation.
    await expect(
      page.getByText("Steered in.", { exact: true }).first(),
    ).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Pantry stocked.").first()).toBeVisible({
      timeout: 60_000,
    });
  });
});
