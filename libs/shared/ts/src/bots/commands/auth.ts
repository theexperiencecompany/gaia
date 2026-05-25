/**
 * Unified `/auth` command — links a platform account to GAIA.
 *
 * Checks whether the user is already linked. If so, tells them.
 * Otherwise generates a one-time link token and shows the auth URL.
 *
 * @module
 */
import type { BotCommand, CommandExecuteParams } from "../types";
import { buildAuthLinkMessage } from "../utils/formatters";

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
      await target.sendEphemeral(buildAuthLinkMessage(authUrl));
    } catch {
      await target.sendEphemeral(
        "❌ Failed to generate auth link. Please try again.",
      );
    }
  },
};
