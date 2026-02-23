/**
 * Registers Telegram bot commands with the Telegram API.
 *
 * Pushes the current {@link allCommands} list to Telegram so the "/" suggestion
 * menu in every Telegram client shows up-to-date commands. Run this whenever
 * commands are added, removed, or renamed.
 *
 * Run with: `pnpm set-commands` or `tsx src/set-commands.ts`
 */

import { allCommands } from "@gaia/shared";
import { Bot } from "grammy";

const token = process.env.TELEGRAM_BOT_TOKEN;

if (!token) {
  console.error("Missing TELEGRAM_BOT_TOKEN");
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
    console.log(
      `Successfully registered ${commands.length} Telegram bot commands:`,
    );
    for (const cmd of commands) {
      console.log(`  /${cmd.command} — ${cmd.description}`);
    }
  } catch (error) {
    console.error("Failed to register Telegram bot commands:", error);
    process.exit(1);
  }
})();
