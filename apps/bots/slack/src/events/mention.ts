import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { App } from "@slack/bolt";

export function registerMentionEvent(app: App, gaia: GaiaClient) {
  app.event("app_mention", async ({ event, say }) => {
    const content = event.text.replace(/<@[^>]+>/g, "").trim();
    const userId = event.user;

    if (!userId) return;

    if (!content) {
      await say("How can I help you?");
      return;
    }

    try {
      const response = await gaia.chatPublic({
        message: content,
        platform: "slack",
        platformUserId: userId,
      });

      const truncated = truncateResponse(response.response, "slack");
      await say(truncated);
    } catch (error) {
      await say(formatError(error));
    }
  });
}
