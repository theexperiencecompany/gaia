import type { Bot } from "grammy";
import type { GaiaClient } from "@gaia/shared";

/**
 * Registers the /auth command handler.
 * Provides a link for users to authenticate their Telegram account with GAIA.
 *
 * @param {Bot} bot - The Telegram Bot instance.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export function registerAuthCommand(bot: Bot, gaia: GaiaClient) {
  bot.command("auth", async (ctx) => {
    const userId = ctx.from?.id.toString();
    if (!userId) return;

    const authUrl = gaia.getAuthUrl("telegram", userId);
    await ctx.reply(`Click to link your Telegram account to GAIA: ${authUrl}`);
  });
}
