import type {
  BotCommand,
  GaiaClient,
  Platform,
  PlatformBot,
} from "@gaia/shared";
import { Bot } from "grammy";
import { registerCommands } from "./commands";
import { registerHandlers } from "./handlers";

export class TelegramBot implements PlatformBot {
  readonly platform: Platform = "telegram";
  private bot: Bot;
  private gaia: GaiaClient;

  constructor(gaia: GaiaClient) {
    const token = process.env.TELEGRAM_BOT_TOKEN;

    if (!token) {
      throw new Error("TELEGRAM_BOT_TOKEN is required");
    }

    this.gaia = gaia;
    this.bot = new Bot(token);

    this.bot.catch((err) => {
      console.error("Bot error:", err);
    });
  }

  registerCommands(_commands: BotCommand[]): void {
    registerCommands(this.bot, this.gaia);
    registerHandlers(this.bot, this.gaia);
  }

  async start(): Promise<void> {
    this.registerCommands([]);
    this.bot.start({
      onStart: () => console.log("Telegram bot is running"),
    });
  }

  async stop(): Promise<void> {
    await this.bot.stop();
  }
}
