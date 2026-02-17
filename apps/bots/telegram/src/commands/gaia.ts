import type { Bot } from "grammy";
import type { GaiaClient } from "@gaia/shared";
import { splitMessage, formatError } from "@gaia/shared";

export function registerGaiaCommand(bot: Bot, gaia: GaiaClient) {
  bot.command("gaia", async (ctx) => {
    const message = ctx.match;
    const userId = ctx.from?.id.toString();
    const chatId = ctx.chat.id.toString();

    if (!userId) {
      await ctx.reply("Could not identify your user.");
      return;
    }

    if (!message) {
      await ctx.reply("Usage: /gaia <your message>");
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

      const chunks = splitMessage(response.response, "telegram");
      for (const chunk of chunks) {
        await ctx.reply(chunk);
      }
    } catch (error) {
      await ctx.reply(formatError(error));
    }
  });
}
