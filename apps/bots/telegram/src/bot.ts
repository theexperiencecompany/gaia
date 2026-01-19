import { Bot } from "grammy";
import { GaiaClient, loadConfig } from "@gaia/shared";
import { registerCommands } from "./commands";
import { registerHandlers } from "./handlers";

/**
 * Initializes and starts the Telegram bot.
 * Sets up middleware, commands, and handlers.
 *
 * @returns {Promise<Bot>} The initialized Telegram Bot instance.
 * @throws {Error} If TELEGRAM_BOT_TOKEN is missing.
 */
export async function createBot() {
  const config = loadConfig();
  const token = process.env.TELEGRAM_BOT_TOKEN;

  if (!token) {
    throw new Error("TELEGRAM_BOT_TOKEN is required");
  }

  const bot = new Bot(token);
  const gaia = new GaiaClient(config.gaiaApiUrl, config.gaiaApiKey);

  registerCommands(bot, gaia);
  registerHandlers(bot, gaia);

  bot.catch((err) => {
    console.error("Bot error:", err);
  });

  bot.start({
    onStart: () => console.log("Telegram bot is running")
  });

  return bot;
}
