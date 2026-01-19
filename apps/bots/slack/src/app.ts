import { App } from "@slack/bolt";
import { GaiaClient, loadConfig } from "@gaia/shared";
import { registerCommands } from "./commands";
import { registerEvents } from "./events";

/**
 * Initializes and starts the Slack bot application.
 * Sets up command listeners, event listeners, and proper configuration.
 *
 * @returns {Promise<App>} The initialized Slack App instance.
 * @throws {Error} If SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, or SLACK_APP_TOKEN are missing.
 */
export async function createApp() {
  const config = loadConfig();

  const token = process.env.SLACK_BOT_TOKEN;
  const signingSecret = process.env.SLACK_SIGNING_SECRET;
  const appToken = process.env.SLACK_APP_TOKEN;

  if (!token || !signingSecret || !appToken) {
    throw new Error("Missing SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, or SLACK_APP_TOKEN");
  }

  const app = new App({
    token,
    signingSecret,
    socketMode: true,
    appToken
  });

  const gaia = new GaiaClient(config.gaiaApiUrl, config.gaiaApiKey);

  registerCommands(app, gaia);
  registerEvents(app, gaia);

  await app.start();
  console.log("Slack bot is running");

  return app;
}
