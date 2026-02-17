import type { Bot } from "grammy";
import type { GaiaClient } from "@gaia/shared";
import { splitMessage, formatError } from "@gaia/shared";

export function registerGroupHandler(bot: Bot, gaia: GaiaClient) {
  bot.on("message:text", async (ctx, next) => {
    const chatType = ctx.chat.type;
    if (chatType !== "group" && chatType !== "supergroup") {
      return next();
    }

    const botUsername = ctx.me.username;
    if (!botUsername || !ctx.message.text.includes(`@${botUsername}`)) {
      return next();
    }

    // Strip only the bot's own @mention so user references remain intact
    const content = ctx.message.text
      .replace(new RegExp(`@${botUsername}`, "g"), "")
      .trim();

    if (!content) {
      await ctx.reply("How can I help you?");
      return;
    }

    const userId = ctx.from?.id.toString();
    if (!userId) {
      await ctx.reply("Could not identify your user.");
      return;
    }

    try {
      await ctx.replyWithChatAction("typing");

      const response = await gaia.chat({
        message: content,
        platform: "telegram",
        platformUserId: userId,
        channelId: ctx.chat.id.toString(),
        publicContext: true,
      });

      if (!response.authenticated) {
        const authUrl = gaia.getAuthUrl("telegram", userId);
        await ctx.reply(`Please link your account first: ${authUrl}`);
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
