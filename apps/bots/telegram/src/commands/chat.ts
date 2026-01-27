import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { Bot, Context } from "grammy";

export function registerChatCommand(bot: Bot, gaia: GaiaClient) {
  bot.command("chat", async (ctx: Context) => {
    const message =
      typeof ctx.match === "string" ? ctx.match : ctx.match?.join(" ");
    const userId = ctx.from?.id.toString();
    const chatId = ctx.chat?.id.toString();

    if (!userId || !chatId) return;

    if (!message) {
      await ctx.reply("Usage: /chat <your message>");
      return;
    }

    try {
      await ctx.replyWithChatAction("typing");

      const response = await gaia.chat({
        message,
        platform: "telegram",
        platformUserId: userId,
        channelId: chatId,
      });

      if (!response.authenticated) {
        const authUrl = gaia.getAuthUrl();
        await ctx.reply(
          `🔗 Link your Telegram account to GAIA to chat:\n${authUrl}\n\nSign in to GAIA and connect Telegram in Settings → Linked Accounts.`,
        );
        return;
      }

      const truncated = truncateResponse(response.response, "telegram");
      await ctx.reply(truncated);
    } catch (error) {
      await ctx.reply(formatError(error));
    }
  });
}
