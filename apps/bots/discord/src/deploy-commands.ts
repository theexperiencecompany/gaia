/**
 * Registers Discord slash commands and context menu commands with the Discord API.
 *
 * Converts unified {@link BotCommand} definitions from the shared library
 * into Discord `SlashCommandBuilder` objects and deploys them globally
 * via the Discord REST API. Also registers context menu commands for
 * right-click message actions.
 *
 * Run with: `pnpm deploy-commands` or `tsx src/deploy-commands.ts`
 */

import { allCommands, type BotCommand } from "@gaia/shared";
import {
  ApplicationCommandType,
  ContextMenuCommandBuilder,
  REST,
  Routes,
  type SlashCommandBooleanOption,
  SlashCommandBuilder,
  type SlashCommandIntegerOption,
  type SlashCommandStringOption,
} from "discord.js";

/**
 * Converts a unified {@link BotCommand} definition into a Discord
 * `SlashCommandBuilder` JSON payload.
 *
 * Handles three command shapes:
 * 1. Simple commands with no options (e.g. `/new`, `/help`)
 * 2. Commands with top-level options (e.g. `/gaia <message>`)
 * 3. Commands with subcommands (e.g. `/todo list`, `/todo add <title>`)
 *
 * @param cmd - The unified command definition.
 * @returns The Discord slash command JSON payload.
 */
function buildSlashCommand(
  cmd: BotCommand,
): ReturnType<SlashCommandBuilder["toJSON"]> {
  const builder = new SlashCommandBuilder()
    .setName(cmd.name)
    .setDescription(cmd.description);

  if (cmd.subcommands && cmd.subcommands.length > 0) {
    for (const sub of cmd.subcommands) {
      builder.addSubcommand((subBuilder) => {
        subBuilder.setName(sub.name).setDescription(sub.description);
        if (sub.options) {
          for (const opt of sub.options) {
            addOption(subBuilder, opt);
          }
        }
        return subBuilder;
      });
    }
  } else if (cmd.options) {
    for (const opt of cmd.options) {
      addOption(builder, opt);
    }
  }

  return builder.toJSON();
}

/**
 * Adds a typed option to a Discord slash command or subcommand builder.
 */
function addOption(
  builder: {
    addStringOption: (
      fn: (o: SlashCommandStringOption) => SlashCommandStringOption,
    ) => unknown;
    addIntegerOption: (
      fn: (o: SlashCommandIntegerOption) => SlashCommandIntegerOption,
    ) => unknown;
    addBooleanOption: (
      fn: (o: SlashCommandBooleanOption) => SlashCommandBooleanOption,
    ) => unknown;
  },
  opt: NonNullable<BotCommand["options"]>[number],
): void {
  if (opt.type === "integer") {
    builder.addIntegerOption((o) => {
      o.setName(opt.name).setDescription(opt.description);
      if (opt.required) o.setRequired(true);
      return o;
    });
  } else if (opt.type === "boolean") {
    builder.addBooleanOption((o) => {
      o.setName(opt.name).setDescription(opt.description);
      if (opt.required) o.setRequired(true);
      return o;
    });
  } else {
    builder.addStringOption((o) => {
      o.setName(opt.name).setDescription(opt.description);
      if (opt.required) o.setRequired(true);
      if (opt.choices) {
        o.addChoices(...opt.choices);
      }
      return o;
    });
  }
}

/** Context menu commands registered as right-click actions on messages. */
const CONTEXT_MENU_COMMANDS = [
  new ContextMenuCommandBuilder()
    .setName("Summarize with GAIA")
    .setType(ApplicationCommandType.Message)
    .toJSON(),
  new ContextMenuCommandBuilder()
    .setName("Add as Todo")
    .setType(ApplicationCommandType.Message)
    .toJSON(),
];

/** Builds all unified commands into Discord slash command payloads. */
export function buildAllCommands() {
  return [...allCommands.map(buildSlashCommand), ...CONTEXT_MENU_COMMANDS];
}

// Only run deployment when executed directly (not imported)
const isMain =
  typeof process !== "undefined" &&
  process.argv[1] &&
  (process.argv[1].endsWith("deploy-commands.ts") ||
    process.argv[1].endsWith("deploy-commands.js"));

if (isMain) {
  const commands = buildAllCommands();
  const token = process.env.DISCORD_BOT_TOKEN;
  const clientId = process.env.DISCORD_CLIENT_ID;

  if (!token || !clientId) {
    console.error("Missing DISCORD_BOT_TOKEN or DISCORD_CLIENT_ID");
    process.exit(1);
  }

  const rest = new REST().setToken(token);

  (async () => {
    try {
      console.log("Registering slash and context menu commands...");
      await rest.put(Routes.applicationCommands(clientId), { body: commands });
      console.log("Successfully registered all commands");
    } catch (error) {
      console.error("Failed to register commands:", error);
      process.exit(1);
    }
  })();
}
