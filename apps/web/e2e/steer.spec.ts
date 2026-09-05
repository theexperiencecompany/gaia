import { expect, test } from "@playwright/test";
import { SIM_ENABLED } from "./harness";

const COMPOSER_PLACEHOLDER = "What can I do for you today?";

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
 * The second POST must START before the first POST's response FINISHES —
 * that ordering is exactly what the old client queue made impossible (it
 * held the send until the turn ended). The backend then folds the steered
 * turn into the live run.
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
    const finished = new Map<string, number>();
    page.on("request", (request) => {
      if (
        request.url().includes("/chat-stream") &&
        request.method() === "POST"
      ) {
        try {
          const body = JSON.parse(request.postData() ?? "{}") as {
            turn_id?: string;
          };
          if (body.turn_id) started.set(body.turn_id, Date.now());
        } catch {
          // Non-JSON body — not a chat turn we can correlate.
        }
      }
    });
    page.on("requestfinished", (req) => {
      const url = req.url();
      if (!url.includes("/chat-stream")) return;
      try {
        const body = JSON.parse(req.postData() ?? "{}") as {
          turn_id?: string;
        };
        if (body.turn_id) finished.set(body.turn_id, Date.now());
      } catch {
        // Ignore uncorrelated finishes.
      }
    });

    await composer.fill(LONG_TASK);
    await composer.press("Enter");

    // Wait until turn 1 truly streams mid-run: the bind navigates to the
    // conversation route (init frame processed), and a mid-list tool card
    // proves the tool loop is underway — not just the echoed user bubble
    // (which contains the directive text and matches instantly).
    await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}/, { timeout: 60_000 });
    await expect(page.getByText("pantry-6").first()).toBeVisible({
      timeout: 60_000,
    });

    await composer.fill(STEER_MESSAGE);
    await composer.press("Enter");

    await expect
      .poll(() => started.size, { timeout: 30_000 })
      .toBeGreaterThanOrEqual(2);

    const [first, second] = [...started.keys()];
    expect(second, "steer is its own turn").not.toBe(first);
    expect(
      started.get(second),
      "second POST starts while the first still streams",
    ).toBeLessThan(finished.get(first) ?? Number.POSITIVE_INFINITY);

    // Both answers render in the same conversation.
    await expect(
      page.getByText("Steered in.", { exact: true }).first(),
    ).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Pantry stocked.").first()).toBeVisible({
      timeout: 60_000,
    });
  });
});
