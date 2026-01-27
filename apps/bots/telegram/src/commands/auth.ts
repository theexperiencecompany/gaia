import type { GaiaClient } from "@gaia/shared";
import type { Bot, Context } from "grammy";

export function registerAuthCommand(bot: Bot, gaia: GaiaClient) {
  bot.command("auth", async (ctx: Context) => {
    const authUrl = gaia.getAuthUrl();
    await ctx.reply(
      `🔗 Link your Telegram account to GAIA:\n${authUrl}\n\nSign in to GAIA and connect Telegram in Settings → Linked Accounts.`,
    );
  });
}
