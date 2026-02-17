import type { Bot } from "grammy";

export function registerStartCommand(bot: Bot) {
  bot.command("start", async (ctx) => {
    await ctx.reply(
      "Welcome to GAIA!\n\n" +
        "Commands:\n" +
        "/gaia <message> - Chat with GAIA\n" +
        "/auth - Link your Telegram account\n" +
        "/new - Start a new conversation\n\n" +
        "You can also send messages directly in private chats, " +
        "or @mention GAIA in group chats.",
    );
  });
}
