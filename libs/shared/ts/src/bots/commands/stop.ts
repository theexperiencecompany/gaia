/**
 * Unified `/stop` command — stops everything the conversation is running.
 *
 * Cancels the reply in progress and the background work it started (the
 * executor, its subagents, pending approvals and the browser task). The session
 * stays: the next message continues the same conversation. `/new` starts fresh.
 *
 * @module
 */
import type { BotCommand, CommandExecuteParams } from "../types";
import { reportCommandFailure } from "../utils/commands";

/** `/stop` command definition. */
export const stopCommand: BotCommand = {
  name: "stop",
  description: "Stop the current reply and any work running in the background",

  async execute({ gaia, target, ctx }: CommandExecuteParams): Promise<void> {
    try {
      await gaia.stopConversation(
        ctx.platform,
        ctx.platformUserId,
        ctx.channelId,
        ctx.isDm,
      );
      await target.sendEphemeral("⏹️ Stopped.");
    } catch (error) {
      await target.sendEphemeral(
        reportCommandFailure("stop_conversation", error, ctx),
      );
    }
  },
};
