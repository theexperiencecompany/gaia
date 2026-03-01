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
import {
  dispatchWorkflowSubcommand,
  handleWorkflowCreate,
} from "../utils/commands";
import { parseTextArgs } from "../utils";
import type { BotCommand, CommandExecuteParams } from "../types";
import { resolveSubcommand, sendTruncated } from "./shared";

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
          name: "name",
          description: "Workflow name",
          required: true,
          type: "string",
        },
        {
          name: "description",
          description: "Workflow description",
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
    const subcommand = resolveSubcommand(args, rawText);
    const subArgs = rawText ? parseTextArgs(rawText).args : [];

    // Handle `create` subcommand specially since it's not in dispatchWorkflowSubcommand
    if (subcommand === "create") {
      let name: string;
      let description: string | undefined;

      if (args.name) {
        name = String(args.name);
        description = args.description ? String(args.description) : undefined;
      } else if (subArgs.length > 0) {
        name = subArgs[0];
        description = subArgs.slice(1).join(" ") || undefined;
      } else {
        await target.sendEphemeral(
          "Usage: /workflow create <name> <description>",
        );
        return;
      }

      const response = await handleWorkflowCreate(gaia, name, ctx, description);
      await sendTruncated(response, target);
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
    await sendTruncated(response, target);
  },
};
