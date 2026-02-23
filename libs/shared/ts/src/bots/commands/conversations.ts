/**
 * Unified `/conversations` command — lists the user's recent conversations.
 *
 * Uses a `list` subcommand with an optional `page` argument for pagination,
 * matching the Discord slash command structure. Text-based platforms (Slack,
 * Telegram) parse the page number from the raw text.
 *
 * Delegates to the shared `handleConversationList` handler.
 *
 * @module
 */
import { handleConversationList } from "../utils/commands";
import { truncateResponse } from "../utils";
import type { BotCommand, CommandExecuteParams } from "../types";

/** `/conversations` command definition. */
export const conversationsCommand: BotCommand = {
  name: "conversations",
  description: "View your GAIA conversations",
  subcommands: [
    {
      name: "list",
      description: "List your recent conversations",
      options: [
        {
          name: "page",
          description: "Page number",
          type: "integer",
        },
      ],
    },
  ],

  async execute({
    gaia,
    target,
    ctx,
    args,
    rawText,
  }: CommandExecuteParams): Promise<void> {
    let page = 1;

    // Discord: page comes from structured args
    if (typeof args.page === "number") {
      page = args.page;
    } else if (rawText) {
      // Text platforms: extract last numeric token from rawText
      // Handles both "/conversations 2" (rawText="2") and "/conversations list 2" (rawText="list 2")
      const tokens = rawText.trim().split(/\s+/);
      const lastToken = tokens[tokens.length - 1];
      const parsed = Number(lastToken);
      if (Number.isInteger(parsed) && parsed > 0) {
        page = parsed;
      }
    }

    const response = await handleConversationList(gaia, ctx, page);
    const truncated = truncateResponse(response, target.platform);
    await target.sendEphemeral(truncated);
  },
};
