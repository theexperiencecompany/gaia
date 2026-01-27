import type { GaiaClient } from "@gaia/shared";
import type { App } from "@slack/bolt";

export function registerAuthCommand(app: App, gaia: GaiaClient) {
  app.command("/auth", async ({ ack, respond }) => {
    await ack();

    const authUrl = gaia.getAuthUrl();

    await respond({
      text: `🔗 Link your Slack account to GAIA:\n${authUrl}\n\nSign in to GAIA and connect Slack in Settings → Linked Accounts.`,
      response_type: "ephemeral",
    });
  });
}
