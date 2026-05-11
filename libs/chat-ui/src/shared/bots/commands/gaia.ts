/**
 * Unified `/gaia` command metadata.
 *
 * The `/gaia` command is special: it requires platform-specific streaming
 * wiring that differs between Discord (ephemeral deferred reply + followUp),
 * Slack (`chat.postMessage` + `chat.update`), and Telegram (`reply` + `editMessageText`).
 *
 * Because of this, the `execute` function here is a **no-op stub**. Each adapter
 * special-cases the `"gaia"` command name and routes to its own
 * `handleChat()` / streaming implementation instead. This command object
 * is used only for:
 * - Metadata (name, description, options) consumed by `deploy-commands.ts`
 * - Inclusion in `allCommands` so `/help` can list it
 *
 * @module
 */
import type { BotCommand } from "../types";

/** `/gaia` command definition (metadata only — execution handled by adapters). */
export const gaiaCommand: BotCommand = {
  name: "gaia",
  description: "Chat with GAIA",
  options: [
    {
      name: "message",
      description: "Your message to GAIA",
      required: true,
      type: "string",
    },
  ],

  async execute(): Promise<void> {
    // Execution is handled by the adapter's handleChat() method.
    // This stub exists so the command can be registered for metadata purposes.
  },
};
