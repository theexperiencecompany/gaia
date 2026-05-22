import { siteConfig } from "@/lib/seo";

export type BotPlatform = "discord" | "telegram" | "slack" | "whatsapp";

export const BOT_LINKS: Record<BotPlatform, string> = {
  discord: `${siteConfig.url}/discord-bot`,
  telegram: "https://t.me/heygaia_bot",
  slack: "/slack-bot",
  whatsapp: "https://wa.me/12762088737",
};

export interface BotAction {
  label: string;
  href: string;
  external?: boolean;
}

export interface BotConfig {
  id: BotPlatform;
  icon: string;
  name: string;
  description: string;
  badge: {
    label: string;
    color: "warning" | "success" | "primary" | "default" | "secondary";
  };
  primaryAction?: BotAction;
  secondaryAction?: BotAction;
}

export const BOTS: BotConfig[] = [
  {
    id: "discord",
    icon: "/images/icons/macos/discord.webp",
    name: "Discord",
    description:
      "Add GAIA to any server or chat one-on-one. Use slash commands, @mention in any channel, or DM for personal help.",
    badge: { label: "Beta", color: "success" },
    primaryAction: {
      label: "Add to Server",
      href: BOT_LINKS.discord,
      external: true,
    },
    secondaryAction: {
      label: "Join Community",
      href: "https://discord.heygaia.io",
      external: true,
    },
  },
  {
    id: "telegram",
    icon: "/images/icons/macos/telegram.webp",
    name: "Telegram",
    description:
      "Just open a chat with @heygaia_bot and start talking. No setup, no group required — it's just you and GAIA.",
    badge: { label: "Beta", color: "success" },
    primaryAction: {
      label: "Start Chatting",
      href: BOT_LINKS.telegram,
      external: true,
    },
    secondaryAction: {
      label: "Read the Docs",
      href: "https://docs.heygaia.io/bots/telegram",
      external: true,
    },
  },
  {
    id: "slack",
    icon: "/images/icons/macos/slack.webp",
    name: "Slack",
    description:
      "Bring GAIA into your workspace. Delegate tasks, run workflows, and get answers — all inside Slack.",
    badge: { label: "Beta", color: "success" },
    primaryAction: {
      label: "Add to Workspace",
      href: BOT_LINKS.slack,
    },
  },
  {
    id: "whatsapp",
    icon: "/images/icons/macos/whatsapp.webp",
    name: "WhatsApp",
    description:
      "Talk to GAIA on the app already on your phone. Ask questions, delegate tasks — no new accounts, no new habits.",
    badge: { label: "Beta", color: "success" },
    primaryAction: {
      label: "Start Chatting",
      href: BOT_LINKS.whatsapp,
      external: true,
    },
    secondaryAction: {
      label: "Join Community",
      href: "https://whatsapp.heygaia.io",
      external: true,
    },
  },
];
