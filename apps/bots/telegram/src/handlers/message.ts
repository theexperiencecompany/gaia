import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { Bot } from "grammy";

export function registerMessageHandler(bot: Bot, gaia: GaiaClient) {
  bot.on("message:text", async (ctx) => {
    if (ctx.message.text.startsWith("/")) return;
    if (ctx.chat.type !== "private") return;

    const userId = ctx.from?.id.toString();
    if (!userId) return;

    try {
      await ctx.replyWithChatAction("typing");

      const response = await gaia.chat({
        message: ctx.message.text,
        platform: "telegram",
        platformUserId: userId,
        channelId: ctx.chat.id.toString(),
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
