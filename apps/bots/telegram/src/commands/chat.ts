import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { Bot } from "grammy";

/**
 * Registers the /chat command handler.
 * Allows users to chat with the GAIA agent directly.
 *
 * @param {Bot} bot - The Telegram Bot instance.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export function registerChatCommand(bot: Bot, gaia: GaiaClient) {
  bot.command("chat", async (ctx) => {
    const message = ctx.match;
    const userId = ctx.from?.id.toString();
    const chatId = ctx.chat.id.toString();

    if (!userId) return;

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
        const authUrl = gaia.getAuthUrl("telegram", userId);
        await ctx.reply(`Please authenticate first: ${authUrl}`);
        return;
      }

      const truncated = truncateResponse(response.response, "telegram");
      await ctx.reply(truncated);
    } catch (error) {
      await ctx.reply(formatError(error));
    }
  });
}
