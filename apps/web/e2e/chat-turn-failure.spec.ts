import { randomUUID } from "node:crypto";
import { expect, type Page, test } from "@playwright/test";
import { SIM_ENABLED } from "./harness";

const COMPOSER_PLACEHOLDER = "What can I do for you today?";
const PROGRESS_TEXT = "Here is the streamed progress";
// The route error page that used to replace the whole conversation.
const ROUTE_ERROR_HEADING = "Something went wrong";

const sseFrame = (payload: unknown): string =>
  `data: ${JSON.stringify(payload)}\n\n`;

async function send(page: Page, message: string): Promise<void> {
  await page.goto("/c");
  const composer = page.getByPlaceholder(COMPOSER_PLACEHOLDER, {
    exact: false,
  });
  await expect(composer).toBeVisible();
  await composer.fill(message);
  await composer.press("Enter");
}

/**
 * A turn that fails part-way must leave what it already showed on screen,
 * with the failure under it — never blank the conversation.
 */
test.describe("chat turn failure", () => {
  test("a card that throws while rendering leaves the rest of the turn on screen", async ({
    page,
  }) => {
    // The stream is canned so one card can carry a payload it cannot render
    // (a calendar card handed a string instead of a list).
    await page.route("**/chat-stream", async (route) => {
      const request = route.request().postDataJSON() as {
        turn_id: string;
        message: string;
      };
      const body = [
        {
          conversation_id: randomUUID(),
          conversation_description: "New Chat",
          user_message_id: request.turn_id,
          user_message_content: request.message,
          bot_message_id: randomUUID(),
          stream_id: randomUUID(),
        },
        { response: PROGRESS_TEXT },
        {
          tool_data: {
            tool_name: "calendar_options",
            data: "not-a-list",
            timestamp: new Date().toISOString(),
          },
        },
      ]
        .map(sseFrame)
        .join("");
      await route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body,
      });
    });

    await send(page, "show my calendar");

    await expect(page.getByText(PROGRESS_TEXT)).toBeVisible();
    await expect(
      page.getByText("This part couldn't be displayed"),
    ).toBeVisible();
    await expect(page.getByText(ROUTE_ERROR_HEADING)).toHaveCount(0);
  });

  test("a model failure mid-reply keeps the streamed text and tool cards, with a retry", async ({
    page,
  }) => {
    test.skip(
      !SIM_ENABLED,
      "Requires the deterministic sim stack. Run `mise dev --sim` and set E2E_SIM=1.",
    );

    await send(
      page,
      `[[tool:create_todo {"title":"turn-failure todo"}]] [[say:${PROGRESS_TEXT}]] [[fail:provider dropped the stream]]`,
    );

    const reply = page.locator(".chatbubblebot_parent").first();
    await expect(reply.getByText("Response was cut short")).toBeVisible({
      timeout: 60_000,
    });
    await expect(reply.getByText(PROGRESS_TEXT).first()).toBeVisible();
    await expect(reply.getByText(/Used \d+ tools?/)).toBeVisible();
    await expect(reply.getByRole("button", { name: "Retry" })).toBeVisible();
  });
  test("a reply the model retried after a failure shows its text once", async ({
    page,
  }) => {
    test.skip(
      !SIM_ENABLED,
      "Requires the deterministic sim stack. Run `mise dev --sim` and set E2E_SIM=1.",
    );
    const replyText = "Streamed before the provider failed";

    // The stub breaks every attempt after its text, so the model call is retried
    // and each attempt streams the same words.
    await send(
      page,
      `[[say:${replyText}]] [[fail:provider dropped the stream]]`,
    );

    const reply = page.locator(".chatbubblebot_parent").first();
    await expect(reply.getByText("Response was cut short")).toBeVisible({
      timeout: 60_000,
    });
    const shown = await reply.innerText();
    expect(shown.split(replyText).length - 1).toBe(1);
  });
});
