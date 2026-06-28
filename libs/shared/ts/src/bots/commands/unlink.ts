/**
 * Unified `/unlink` command — disconnects the platform account from GAIA.
 *
 * Checks auth status first. If not linked, tells the user. If linked,
 * calls the unlink endpoint and confirms the disconnection.
 *
 * @module
 */
import type { BotCommand, CommandExecuteParams } from "../types";
import { createBotLogger } from "../utils/logger";

const logger = createBotLogger("shared", "command:unlink");

/** `/unlink` command definition. */
export const unlinkCommand: BotCommand = {
  name: "unlink",
  description: "Disconnect your account from GAIA",

  async execute({ gaia, target, ctx }: CommandExecuteParams): Promise<void> {
    const status = await gaia.checkAuthStatus(ctx.platform, ctx.platformUserId);

    if (!status.authenticated) {
      await target.sendEphemeral(
        "ℹ️ Your account is not connected to GAIA.\n\n" +
          "Use `/auth` to link your account.",
      );
      return;
    }

    try {
      await gaia.unlinkAccount(ctx.platform, ctx.platformUserId);
      await target.sendEphemeral(
        "✅ **Account Disconnected**\n\n" +
          "Your account has been unlinked from GAIA.\n" +
          "Use `/auth` to reconnect at any time.",
      );
    } catch (error) {
      logger.error("unlink_command_error", undefined, error);
      await target.sendEphemeral(
        "❌ Failed to unlink your account. Please try again.",
      );
    }
  },
};
