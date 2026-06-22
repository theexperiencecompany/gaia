/**
 * Registers Telegram bot commands with the Telegram API.
 *
 * Pushes the current {@link allCommands} list to Telegram so the "/" suggestion
 * menu in every Telegram client shows up-to-date commands. Run this whenever
 * commands are added, removed, or renamed.
 *
 * Run with: `pnpm set-commands` or `tsx src/set-commands.ts`
 */

import { allCommands, createBotLogger } from "@gaia/shared";
import { Bot } from "grammy";

const setCommandsLogger = createBotLogger("telegram", "set-commands");

const token = process.env.TELEGRAM_BOT_TOKEN;

if (!token) {
  setCommandsLogger.error("set_commands_missing_env", {
    missing: ["TELEGRAM_BOT_TOKEN"],
  });
  process.exit(1);
}

const bot = new Bot(token);

// /start is a Telegram convention mapped to /help in the adapter
const commands = [
  { command: "start", description: "Get started with GAIA" },
  ...allCommands.map((cmd) => ({
    command: cmd.name,
    description: cmd.description,
  })),
];

(async () => {
  try {
    await bot.api.setMyCommands(commands);
    setCommandsLogger.info("set_commands_succeeded", {
      command_count: commands.length,
      commands: commands.map((cmd) => `/${cmd.command}`),
    });
  } catch (error) {
    setCommandsLogger.error("set_commands_failed", undefined, error);
    process.exit(1);
  }
})();
