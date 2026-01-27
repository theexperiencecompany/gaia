import type { GaiaClient, Platform, PlatformBot } from "@gaia/shared";
import { App } from "@slack/bolt";
import { registerCommands } from "./commands";
import { registerEvents } from "./events";

export class SlackBot implements PlatformBot {
  readonly platform: Platform = "slack";
  private app: App;
  private gaia: GaiaClient;

  constructor(gaia: GaiaClient) {
    const token = process.env.SLACK_BOT_TOKEN;
    const signingSecret = process.env.SLACK_SIGNING_SECRET;
    const appToken = process.env.SLACK_APP_TOKEN;

    if (!token || !signingSecret || !appToken) {
      throw new Error(
        "Missing SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, or SLACK_APP_TOKEN",
      );
    }

    this.gaia = gaia;
    this.app = new App({
      token,
      signingSecret,
      socketMode: true,
      appToken,
    });
  }

  async start(): Promise<void> {
    registerCommands(this.app, this.gaia);
    registerEvents(this.app, this.gaia);
    await this.app.start();
    console.log("Slack bot is running");
  }

  async stop(): Promise<void> {
    await this.app.stop();
  }
}
