import type { App } from "@slack/bolt";

export function registerHelpCommand(app: App) {
  app.command("/help", async ({ ack, respond }) => {
    await ack();

    await respond({
      text:
        "*GAIA Commands*\n\n" +
        "`/gaia <message>` — Chat with GAIA\n" +
        "`/auth` — Link your Slack account\n" +
        "`/new` — Start a new conversation\n" +
        "`/help` — Show this help message\n\n" +
        "You can also @mention GAIA in any channel.",
      response_type: "ephemeral",
    });
  });
}
