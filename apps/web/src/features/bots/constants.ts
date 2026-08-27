import { BOT_PLATFORM_ICONS, type BotPlatform } from "@/config/botPlatforms";
import { siteConfig } from "@/lib/seo";

export type { BotPlatform };

export const BOT_LINKS: Record<BotPlatform, string> = {
  discord: `${siteConfig.url}/discord-bot`,
  telegram: "https://t.me/heygaia_bot",
  slack: "/slack-bot",
  whatsapp: "https://wa.me/12762088737",
  imessage: "/settings/linked-accounts",
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
    icon: BOT_PLATFORM_ICONS.discord,
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
    icon: BOT_PLATFORM_ICONS.telegram,
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
    icon: BOT_PLATFORM_ICONS.slack,
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
    icon: BOT_PLATFORM_ICONS.whatsapp,
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
  {
    id: "imessage",
    icon: BOT_PLATFORM_ICONS.imessage,
    name: "iMessage",
    description:
      "Text GAIA from the Messages app already on your iPhone. Register your number once, then it's just another conversation in blue bubbles.",
    badge: { label: "Pro", color: "primary" },
    primaryAction: {
      label: "Connect Your Number",
      href: BOT_LINKS.imessage,
    },
    secondaryAction: {
      label: "Read the Docs",
      href: "https://docs.heygaia.io/guides/imessage-bot",
      external: true,
    },
  },
];
