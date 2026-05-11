/**
 * Unified `/help` command — displays available commands and getting-started info.
 *
 * Uses {@link RichMessage} for structured display. Discord renders this as
 * a native embed; Slack and Telegram fall back to formatted markdown.
 *
 * @module
 */
import type { BotCommand, CommandExecuteParams } from "../types";

/** `/help` command definition. */
export const helpCommand: BotCommand = {
  name: "help",
  description: "Learn how to use GAIA and view available commands",

  async execute({ target }: CommandExecuteParams): Promise<void> {
    await target.sendRich({
      type: "embed",
      title: "🤖 GAIA - Your Personal AI Assistant",
      description:
        "GAIA is your proactive AI assistant that helps manage your digital life. Here's how to get started:",
      color: 0x7c3aed,
      fields: [
        {
          name: "✨ Getting Started",
          value: [
            "1. Use `/auth` to link your account with GAIA",
            "2. Once linked, you can use all commands and features",
            "3. Mention @GAIA in any channel for quick questions",
          ].join("\n"),
        },
        {
          name: "📝 Available Commands",
          value: [
            "`/auth` - Link your account to GAIA",
            "`/status` - Check your account link status",
            "`/settings` - View your GAIA settings and integrations",
            "`/gaia <message>` - Chat with GAIA (private)",
            "`/conversations` - View conversation history",
            "`/new` - Start a new conversation",
            "`/stop` - Stop the current response and start fresh",
            "`/todo` - Manage your tasks",
            "`/workflow` - Manage workflows",
            "`/unlink` - Disconnect your account from GAIA",
          ].join("\n"),
        },
        {
          name: "💬 Mention Mode",
          value:
            "Mention @GAIA in any channel to ask questions or get help. Your conversations are remembered!",
        },
      ],
      links: [
        { label: "Website", url: "https://heygaia.io" },
        { label: "Documentation", url: "https://docs.heygaia.io" },
        { label: "Support", url: "https://discord.gg/gaia" },
      ],
      footer: "GAIA - General AI Assistant",
      timestamp: true,
    });
  },
};
