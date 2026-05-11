/**
 * Unified `/stop` command — cancels the active stream and resets the conversation.
 *
 * Resets the bot session so the next message starts a fresh conversation.
 * Any in-flight stream output is discarded on the bot side.
 *
 * @module
 */
import type { BotCommand, CommandExecuteParams } from "../types";

/** `/stop` command definition. */
export const stopCommand: BotCommand = {
  name: "stop",
  description: "Reset your conversation session",

  async execute({ gaia, target, ctx }: CommandExecuteParams): Promise<void> {
    try {
      await gaia.resetSession(ctx.platform, ctx.platformUserId, ctx.channelId);
      await target.sendEphemeral("⏹️ Stopped. Starting a new conversation.");
    } catch {
      await target.sendEphemeral("❌ Failed to stop. Please try again.");
    }
  },
};
