import type { Bot } from "grammy";
import type { GaiaClient } from "@gaia/shared";
import { truncateResponse, formatError } from "@gaia/shared";

/**
 * Registers the text message handler for private chats.
 * Forwards any private message to the GAIA agent (authenticated chat).
 *
 * @param {Bot} bot - The Telegram Bot instance.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
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
        channelId: ctx.chat.id.toString()
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
