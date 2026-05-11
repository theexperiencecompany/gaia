/**
 * Unified `/auth` command — links a platform account to GAIA.
 *
 * Checks whether the user is already linked. If so, tells them.
 * Otherwise generates a one-time link token and shows the auth URL.
 *
 * @module
 */
import type { BotCommand, CommandExecuteParams } from "../types";

/** `/auth` command definition. */
export const authCommand: BotCommand = {
  name: "auth",
  description: "Link your account to GAIA",

  async execute({ gaia, target, ctx }: CommandExecuteParams): Promise<void> {
    const status = await gaia.checkAuthStatus(ctx.platform, ctx.platformUserId);

    if (status.authenticated) {
      await target.sendEphemeral(
        "✅ **Already Connected!**\n\n" +
          "Your account is already linked to GAIA.\n\n" +
          "Use `/settings` to view your account details and connected integrations.",
      );
      return;
    }

    try {
      const { authUrl } = await gaia.createLinkToken(
        ctx.platform,
        ctx.platformUserId,
        ctx.profile,
      );
      // NOTE: Avoid _italic_ markers here — underscores in the URL token
      // pair with them and break Telegram's legacy Markdown parser.
      // And the bare URL is auto-linked by Telegram on real domains (not localhost).
      await target.sendEphemeral(
        "🔗 **Link your account to GAIA**\n\n" +
          "Tap the link below to sign in and link your account:\n" +
          `${authUrl}\n\n` +
          "After linking, you'll be able to use all GAIA commands!",
      );
    } catch {
      await target.sendEphemeral(
        "❌ Failed to generate auth link. Please try again.",
      );
    }
  },
};
