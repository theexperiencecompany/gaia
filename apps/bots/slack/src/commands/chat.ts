import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { App } from "@slack/bolt";

export function registerChatCommand(app: App, gaia: GaiaClient) {
  app.command("/chat", async ({ command, ack, respond }) => {
    await ack();

    const userId = command.user_id;
    const channelId = command.channel_id;
    const message = command.text;

    if (!message) {
      await respond({
        text: "Please provide a message. Usage: /chat <your message>",
        response_type: "ephemeral",
      });
      return;
    }

    try {
      const response = await gaia.chat({
        message,
        platform: "slack",
        platformUserId: userId,
        channelId,
      });

      if (!response.authenticated) {
        const authUrl = gaia.getAuthUrl();
        await respond({
          text: `🔗 Link your Slack account to GAIA to chat:\n${authUrl}\n\nSign in to GAIA and connect Slack in Settings → Linked Accounts.`,
          response_type: "ephemeral",
        });
        return;
      }

      const truncated = truncateResponse(response.response, "slack");
      await respond({
        text: truncated,
        response_type: "ephemeral",
      });
    } catch (error) {
      await respond({
        text: formatError(error),
        response_type: "ephemeral",
      });
    }
  });
}
