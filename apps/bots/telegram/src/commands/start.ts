import type { Bot, Context } from "grammy";

export function registerStartCommand(bot: Bot) {
  bot.command("start", async (ctx: Context) => {
    await ctx.reply(
      "👋 Welcome to GAIA!\n\n" +
        "**Commands:**\n" +
        "/chat <message> - Chat with GAIA\n" +
        "/auth - Link your Telegram account\n\n" +
        "You can also send messages directly in private chats.",
      { parse_mode: "Markdown" },
    );
  });
}
