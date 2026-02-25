/**
 * Unified `/todo` command — manages the user's todo list.
 *
 * Supports subcommands: `list`, `add`, `complete`, `delete`.
 * Delegates to shared handlers in `utils/commands.ts`.
 *
 * For Discord (structured args), the `add` subcommand extracts `priority`
 * and `description` from named options. For text-based platforms, it falls
 * back to `dispatchTodoSubcommand` which parses positional args.
 *
 * @module
 */
import {
  dispatchTodoSubcommand,
  handleTodoCreate,
  handleTodoList,
} from "../utils/commands";
import { truncateResponse, parseTextArgs } from "../utils";
import type { BotCommand, CommandExecuteParams } from "../types";

/** `/todo` command definition with subcommands. */
export const todoCommand: BotCommand = {
  name: "todo",
  description: "Manage your todos",
  subcommands: [
    {
      name: "list",
      description: "List your todos",
      options: [
        {
          name: "completed",
          description: "Show completed todos",
          type: "boolean",
        },
      ],
    },
    {
      name: "add",
      description: "Add a new todo",
      options: [
        {
          name: "title",
          description: "Todo title",
          required: true,
          type: "string",
        },
        {
          name: "priority",
          description: "Priority level",
          type: "string",
          choices: [
            { name: "Low", value: "low" },
            { name: "Medium", value: "medium" },
            { name: "High", value: "high" },
          ],
        },
        {
          name: "description",
          description: "Todo description",
          type: "string",
        },
      ],
    },
    {
      name: "complete",
      description: "Mark a todo as complete",
      options: [
        {
          name: "id",
          description: "Todo ID",
          required: true,
          type: "string",
        },
      ],
    },
    {
      name: "delete",
      description: "Delete a todo",
      options: [
        {
          name: "id",
          description: "Todo ID",
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

    // Structured args path (Discord): handle "add" specially to preserve
    // priority and description options that dispatchTodoSubcommand ignores
    if (args.subcommand && !rawText && subcommand === "add") {
      const title = args.title ? String(args.title) : "";
      if (!title) {
        await target.sendEphemeral("Usage: /todo add <title>");
        return;
      }
      const priority = args.priority as "low" | "medium" | "high" | undefined;
      const description = args.description
        ? String(args.description)
        : undefined;
      const response = await handleTodoCreate(gaia, title, ctx, {
        priority,
        description,
      });
      const truncated = truncateResponse(response, target.platform);
      await target.sendEphemeral(truncated);
      return;
    }

    // Structured args path (Discord): handle "list" with completed flag
    if (args.subcommand && !rawText && subcommand === "list") {
      const completed =
        typeof args.completed === "boolean" ? args.completed : undefined;
      const response = await handleTodoList(gaia, ctx, completed);
      const truncated = truncateResponse(response, target.platform);
      await target.sendEphemeral(truncated);
      return;
    }

    // Structured args path (Discord): build positional args from named options
    if (args.subcommand && !rawText) {
      const subArgs: string[] = [];
      if (args.title) subArgs.push(String(args.title));
      if (args.id) subArgs.push(String(args.id));
      const response = await dispatchTodoSubcommand(
        gaia,
        ctx,
        subcommand,
        subArgs,
      );
      const truncated = truncateResponse(response, target.platform);
      await target.sendEphemeral(truncated);
      return;
    }

    // Text-based path (Slack, Telegram): parse rawText into positional args
    const subArgs = rawText ? parseTextArgs(rawText).args : [];
    const response = await dispatchTodoSubcommand(
      gaia,
      ctx,
      subcommand,
      subArgs,
    );
    const truncated = truncateResponse(response, target.platform);
    await target.sendEphemeral(truncated);
  },
};
