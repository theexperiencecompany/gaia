/**
 * Unified `/new` command — starts a fresh conversation with GAIA.
 *
 * Resets the bot session so subsequent messages go to a new conversation.
 * The previous conversation is preserved and accessible from the web app.
 *
 * @module
 */

import type { BotCommand, CommandExecuteParams } from "../types";
import { handleNewConversation } from "../utils/commands";

/** `/new` command definition. */
export const newCommand: BotCommand = {
  name: "new",
  description: "Start a new conversation with GAIA",

  async execute({ gaia, target, ctx }: CommandExecuteParams): Promise<void> {
    const response = await handleNewConversation(gaia, ctx);
    await target.sendEphemeral(response);
  },
};
