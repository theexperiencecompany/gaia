import type { App } from "@slack/bolt";
import type { GaiaClient } from "@gaia/shared";

/**
 * Registers the /auth slash command listener.
 * Provides a link for users to authenticate their Slack account with GAIA.
 *
 * @param {App} app - The Slack App instance.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export function registerAuthCommand(app: App, gaia: GaiaClient) {
  app.command("/auth", async ({ command, ack, respond }) => {
    await ack();

    const userId = command.user_id;
    const authUrl = gaia.getAuthUrl("slack", userId);

    await respond({
      text: `Click to link your Slack account to GAIA: ${authUrl}`,
      response_type: "ephemeral"
    });
  });
}
