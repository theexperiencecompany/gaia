/**
 * Bot process bootstrap helper.
 *
 * Provides {@link runBot} — a single entry-point that encapsulates the
 * standard startup/shutdown lifecycle shared by every platform bot.
 *
 * @module
 */
import type { BotCommand } from "./types";
import type { BaseBotAdapter } from "./adapter";

/**
 * Boots a bot adapter and wires process-level signal handling.
 *
 * Replaces the boilerplate `main` / `shutdown` pattern that was previously
 * duplicated across every bot's `index.ts`. The function:
 * 1. Calls `adapter.boot(commands)` to start the bot.
 * 2. Registers `SIGINT` and `SIGTERM` handlers that call `adapter.shutdown()`
 *    and exit cleanly.
 * 3. Catches any fatal startup error, logs it, and exits with code 1.
 *
 * @param adapter - A concrete {@link BaseBotAdapter} instance.
 * @param commands - The array of unified {@link BotCommand} definitions to register.
 *
 * @example
 * ```typescript
 * import { allCommands, runBot } from "@gaia/shared";
 * import { DiscordAdapter } from "./adapter";
 *
 * runBot(new DiscordAdapter(), allCommands);
 * ```
 */
export function runBot(adapter: BaseBotAdapter, commands: BotCommand[]): void {
  async function shutdown(): Promise<void> {
    try {
      await adapter.shutdown();
    } catch (err) {
      console.error("Shutdown error:", err);
    }
    process.exit(0);
  }

  process.on("SIGINT", () => void shutdown());
  process.on("SIGTERM", () => void shutdown());

  adapter.boot(commands).catch((err) => {
    console.error("Fatal error:", err);
    process.exit(1);
  });
}
