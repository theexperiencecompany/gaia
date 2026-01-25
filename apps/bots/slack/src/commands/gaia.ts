import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { App } from "@slack/bolt";

/**
 * Registers the /gaia slash command listener.
 * Handles authenticated chat with the GAIA agent.
 *
 * @param {App} app - The Slack App instance.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export function registerGaiaCommand(app: App, gaia: GaiaClient) {
  app.command("/gaia", async ({ command, ack, respond }) => {
    await ack();

    const userId = command.user_id;
    const channelId = command.channel_id;
    const message = command.text;

    if (!message) {
      await respond({
        text: "Please provide a message. Usage: /gaia <your message>",
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
        const authUrl = gaia.getAuthUrl("slack", userId);
        await respond({
          text: `Please authenticate first: ${authUrl}`,
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
