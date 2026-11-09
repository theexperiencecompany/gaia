import { BOT_PLATFORM_ICONS, type BotPlatform } from "@/config/botPlatforms";
import { siteConfig } from "@/lib/seo";

export type { BotPlatform };

/** GAIA Cloud's bots; a self-hosted instance reaches its own through useBotLinks. */
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
  primaryAction?: BotAction;
  secondaryAction?: BotAction;
  /** The command that sets this bot up on a self-hosted instance that runs none yet. */
  setupCommand?: string;
}

export const BOTS: BotConfig[] = [
  {
    id: "discord",
    icon: BOT_PLATFORM_ICONS.discord,
    name: "Discord",
    description:
      "Add GAIA to any server or chat one-on-one. Use slash commands, @mention in any channel, or DM for personal help.",
    primaryAction: {
      label: "Add to Server",
      href: BOT_LINKS.discord,
      external: true,
    },
    secondaryAction: {
      label: "Join Discord server",
      href: "https://discord.heygaia.io",
      external: true,
    },
  },
  {
    id: "telegram",
    icon: BOT_PLATFORM_ICONS.telegram,
    name: "Telegram",
    description:
      "Just open a chat with @heygaia_bot and start talking. No setup, no group required. It's just you and GAIA.",
    primaryAction: {
      label: "Open in Telegram",
      href: BOT_LINKS.telegram,
      external: true,
    },
    secondaryAction: {
      label: "Telegram docs",
      href: "https://docs.heygaia.io/bots/telegram",
      external: true,
    },
  },
  {
    id: "slack",
    icon: BOT_PLATFORM_ICONS.slack,
    name: "Slack",
    description:
      "Bring GAIA into your workspace. Delegate tasks, run workflows, and get answers, all inside Slack.",
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
      "Talk to GAIA on the app already on your phone. Ask questions, delegate tasks. No new accounts, no new habits.",
    primaryAction: {
      label: "Open in WhatsApp",
      href: BOT_LINKS.whatsapp,
      external: true,
    },
    secondaryAction: {
      label: "WhatsApp community",
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
    primaryAction: {
      label: "Connect Your Number",
      href: BOT_LINKS.imessage,
    },
    secondaryAction: {
      label: "iMessage docs",
      href: "https://docs.heygaia.io/guides/imessage-bot",
      external: true,
    },
  },
];

/** The bots a self-hosted instance can run, each added with `gaia bots add`. */
export const SELFHOST_BOT_PLATFORMS = [
  "telegram",
  "discord",
  "slack",
] as const satisfies readonly BotPlatform[];

/** What each self-hosted bot's card says and does; GAIA Cloud's copy names its own bots. */
export const SELFHOST_BOT_COPY: Record<
  (typeof SELFHOST_BOT_PLATFORMS)[number],
  { description: string; actionLabel: string }
> = {
  telegram: {
    description:
      "Chat with your GAIA from Telegram, one-on-one with your instance's bot.",
    actionLabel: "Start Chatting",
  },
  discord: {
    description:
      "Add your instance's bot to a server. Use slash commands, @mention it in a channel, or DM it.",
    actionLabel: "Add to Server",
  },
  slack: {
    description:
      "Delegate tasks, run workflows, and get answers from your instance's bot, inside Slack.",
    actionLabel: "Open Slack",
  },
};

export const SELFHOST_BOTS_DOCS_URL =
  "https://docs.heygaia.io/self-hosting/bots";
