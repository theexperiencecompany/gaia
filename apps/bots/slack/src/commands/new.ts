import type { App } from "@slack/bolt";
import type { GaiaClient } from "@gaia/shared";
import { formatError } from "@gaia/shared";

export function registerNewCommand(app: App, gaia: GaiaClient) {
  app.command("/new", async ({ command, ack, respond }) => {
    await ack();

    try {
      const result = await gaia.newSession(
        "slack",
        command.user_id,
        command.channel_id,
      );
      await respond({
        text: result.message,
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
