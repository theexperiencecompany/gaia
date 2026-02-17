import type { GaiaClient } from "@gaia/shared";
import { formatError, splitMessage } from "@gaia/shared";
import type { App } from "@slack/bolt";

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

      const chunks = splitMessage(response.response, "slack");
      for (const chunk of chunks) {
        await respond({
          text: chunk,
          response_type: "ephemeral",
        });
      }
    } catch (error) {
      await respond({
        text: formatError(error),
        response_type: "ephemeral",
      });
    }
  });
}
