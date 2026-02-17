import type { Bot } from "grammy";
import type { GaiaClient } from "@gaia/shared";
import { formatError } from "@gaia/shared";

export function registerNewCommand(bot: Bot, gaia: GaiaClient) {
  bot.command("new", async (ctx) => {
    const userId = ctx.from?.id.toString();
    if (!userId) {
      await ctx.reply("Could not identify your user.");
      return;
    }

    try {
      const result = await gaia.newSession(
        "telegram",
        userId,
        ctx.chat.id.toString(),
      );
      await ctx.reply(result.message);
    } catch (error) {
      await ctx.reply(formatError(error));
    }
  });
}
