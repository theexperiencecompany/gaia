/**
 * Unified `/help` command — displays available commands and getting-started info.
 *
 * Sent as a {@link Card}, which each platform renders in its native format.
 *
 * @module
 */
import { BOT_URLS } from "../../constants/bots";
import type { BotCommand, CommandExecuteParams } from "../types";

/** `/help` command definition. */
export const helpCommand: BotCommand = {
  name: "help",
  description: "Learn how to use GAIA and view available commands",

  async execute({ gaia, target }: CommandExecuteParams): Promise<void> {
    await target.sendCard({
      title: "Hey, I'm GAIA 👋",
      accent: "brand",
      blocks: [
        {
          kind: "text",
          markdown:
            "Your personal AI. I think ahead, remember what matters, and help you actually get things done. Here's how we work together.",
        },
        {
          kind: "fields",
          fields: [
            {
              label: "Get started",
              value: [
                "**1.** Link your account with `/auth`",
                "**2.** Talk to me anytime with `/gaia <message>`, or just @mention me",
                "**3.** I'll remember our conversations and your context",
              ].join("\n"),
            },
            {
              label: "What I can do",
              value: [
                "`/gaia`: chat with me privately",
                "`/todo`: capture and manage your tasks",
                "`/workflow`: set up and run automations",
                "`/settings`: your account and connected apps",
                "`/status`: check if you're linked",
                "`/new`: start a fresh conversation",
                "`/stop`: cancel the current reply and reset",
                "`/conversations`: pick up a past chat",
                "`/unlink`: disconnect your account",
              ].join("\n"),
            },
            {
              label: "Or just mention me",
              value:
                "@mention me in any channel for a quick question, and I'll keep track of the thread.",
            },
          ],
        },
      ],
      actions: [
        // The instance the bot serves: a self-hosted GAIA, not heygaia.io.
        { kind: "link", label: "Open GAIA", url: gaia.getFrontendUrl() },
        { kind: "link", label: "Docs", url: "https://docs.heygaia.io" },
        { kind: "link", label: "Support", url: BOT_URLS.discord },
      ],
      timestamp: true,
    });
  },
};
