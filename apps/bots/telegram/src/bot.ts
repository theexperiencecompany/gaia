import { Bot } from "grammy";
import { GaiaClient, loadConfig, UserRateLimiter } from "@gaia/shared";
import { registerCommands } from "./commands";
import { registerHandlers } from "./handlers";

export async function createBot() {
  const config = loadConfig();
  const token = process.env.TELEGRAM_BOT_TOKEN;

  if (!token) {
    throw new Error("TELEGRAM_BOT_TOKEN is required");
  }

  const bot = new Bot(token);
  const gaia = new GaiaClient(config.gaiaApiUrl, config.gaiaApiKey);
  const rateLimiter = new UserRateLimiter(20, 60_000);

  // Rate limiting middleware — runs before all commands/handlers
  bot.use(async (ctx, next) => {
    const userId = ctx.from?.id.toString();
    if (userId && !rateLimiter.check(userId)) {
      await ctx.reply(
        "You're sending messages too fast. Please slow down.",
      );
      return;
    }
    return next();
  });

  registerCommands(bot, gaia);
  registerHandlers(bot, gaia);

  bot.catch((err) => {
    console.error("Bot error:", err);
  });

  bot.start({
    onStart: () => console.log("Telegram bot is running"),
  });

  return bot;
}
