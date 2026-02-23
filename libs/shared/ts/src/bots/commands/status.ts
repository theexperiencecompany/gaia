/**
 * Unified `/status` command — checks the user's GAIA account link status.
 *
 * Shows whether the platform account is linked and provides an auth URL
 * if it isn't.
 *
 * @module
 */
import type { BotCommand, CommandExecuteParams } from "../types";

/** `/status` command definition. */
export const statusCommand: BotCommand = {
  name: "status",
  description: "Check your GAIA account link status",

  async execute({ gaia, target, ctx }: CommandExecuteParams): Promise<void> {
    try {
      const status = await gaia.checkAuthStatus(
        ctx.platform,
        ctx.platformUserId,
      );

      if (status.authenticated) {
        await target.sendEphemeral(
          "✅ Your account is linked to GAIA!\n\nYou can use all commands.",
        );
      } else {
        try {
          const { authUrl } = await gaia.createLinkToken(
            ctx.platform,
            ctx.platformUserId,
          );
          await target.sendEphemeral(
            `❌ Not linked yet.\n\n🔗 Link your account: ${authUrl}`,
          );
        } catch {
          await target.sendEphemeral(
            "❌ Not linked yet. Use /auth to link your account.",
          );
        }
      }
    } catch {
      await target.sendEphemeral(
        "Error checking status. Please try again.",
      );
    }
  },
};
