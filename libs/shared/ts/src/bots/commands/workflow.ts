/**
 * Unified `/workflow` command — manages GAIA workflows.
 *
 * Supports subcommands: `list`, `get`, `execute`, `create`.
 * Delegates to shared handlers in `utils/commands.ts`.
 *
 * The `create` subcommand is new for Slack and Telegram (previously Discord-only).
 *
 * @module
 */

import type { BotCommand, CommandExecuteParams } from "../types";
import { parseTextArgs, sendChunked } from "../utils";
import {
  dispatchWorkflowSubcommand,
  handleWorkflowCreate,
} from "../utils/commands";
import { COMMAND_HELP } from "../utils/formatters";

/** `/workflow` command definition with subcommands. */
export const workflowCommand: BotCommand = {
  name: "workflow",
  description: "Manage your GAIA workflows",
  subcommands: [
    { name: "list", description: "List all your workflows" },
    {
      name: "get",
      description: "Get details of a specific workflow",
      options: [
        {
          name: "id",
          description: "Workflow ID",
          required: true,
          type: "string",
        },
      ],
    },
    {
      name: "execute",
      description: "Execute a workflow",
      options: [
        {
          name: "id",
          description: "Workflow ID",
          required: true,
          type: "string",
        },
      ],
    },
    {
      name: "delete",
      description: "Delete a workflow",
      options: [
        {
          name: "id",
          description: "Workflow ID",
          required: true,
          type: "string",
        },
      ],
    },
    {
      name: "create",
      description: "Create a new workflow",
      options: [
        {
          name: "title",
          description: "Workflow title",
          required: true,
          type: "string",
        },
        {
          name: "instructions",
          description: "What GAIA should do each time the workflow runs",
          required: true,
          type: "string",
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
    const subcommand =
      (args.subcommand as string) ||
      (rawText ? parseTextArgs(rawText).subcommand : "list");
    const subArgs = rawText ? parseTextArgs(rawText).args : [];

    // Handle `create` subcommand specially since it's not in dispatchWorkflowSubcommand
    if (subcommand === "create") {
      const title = args.title ? String(args.title) : (subArgs[0] ?? "");
      const instructions = args.instructions
        ? String(args.instructions)
        : subArgs.slice(1).join(" ");
      if (!title || !instructions) {
        await target.sendEphemeral(COMMAND_HELP.workflowUsage.create);
        return;
      }

      const response = await handleWorkflowCreate(
        gaia,
        title,
        instructions,
        ctx,
      );
      await sendChunked(target.sendEphemeral, response, target.platform);
      return;
    }

    // For structured args (Discord), build the args array from named options
    if (args.subcommand && !rawText) {
      if (args.id) subArgs.push(String(args.id));
    }

    const response = await dispatchWorkflowSubcommand(
      gaia,
      ctx,
      subcommand,
      subArgs,
    );
    await sendChunked(target.sendEphemeral, response, target.platform);
  },
};
