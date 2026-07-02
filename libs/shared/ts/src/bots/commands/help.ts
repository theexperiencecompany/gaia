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
      title: "Hey, I'm GAIA 👋",
      description:
        "Your personal AI — I think ahead, remember what matters, and help you actually get things done. Here's how we work together.",
      color: 0x7c3aed,
      fields: [
        {
          name: "Get started",
          value: [
            "**1.** Link your account with `/auth`",
            "**2.** Talk to me anytime with `/gaia <message>`, or just @mention me",
            "**3.** I'll remember our conversations and your context",
          ].join("\n"),
        },
        {
          name: "What I can do",
          value: [
            "`/gaia` — chat with me privately",
            "`/todo` — capture and manage your tasks",
            "`/workflow` — set up and run automations",
            "`/settings` — your account and connected apps",
            "`/status` — check if you're linked",
            "`/new` — start a fresh conversation",
            "`/stop` — cancel the current reply and reset",
            "`/conversations` — pick up a past chat",
            "`/unlink` — disconnect your account",
          ].join("\n"),
        },
        {
          name: "Or just mention me",
          value:
            "@mention me in any channel for a quick question — I'll keep track of the thread.",
        },
      ],
      links: [
        { label: "Website", url: "https://heygaia.io" },
        { label: "Docs", url: "https://docs.heygaia.io" },
        { label: "Support", url: "https://discord.gg/gaia" },
      ],
      timestamp: true,
    });
  },
};
