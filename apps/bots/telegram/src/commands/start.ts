import type { Bot } from "grammy";

/**
 * Registers the /start command handler.
 * Sends a welcome message and a list of available commands.
 *
 * @param {Bot} bot - The Telegram Bot instance.
 */
export function registerStartCommand(bot: Bot) {
  bot.command("start", async (ctx) => {
    await ctx.reply(
      "Welcome to GAIA!\n\n" +
      "Commands:\n" +
      "/gaia <message> - Chat with GAIA\n" +
      "/auth - Link your Telegram account\n\n" +
      "You can also send messages directly in private chats."
    );
  });
}
