import {
  BOT_PLATFORM_IDS,
  type BotPlatform,
} from "@shared/constants/platforms";

export type { BotPlatform };

export const BOT_PLATFORMS = BOT_PLATFORM_IDS;

export const BOT_PLATFORM_LABELS: Record<BotPlatform, string> = {
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  imessage: "iMessage",
  slack: "Slack",
  discord: "Discord",
};

export const BOT_PLATFORM_ICONS: Record<BotPlatform, string> = {
  telegram: "/images/icons/macos/telegram.webp",
  whatsapp: "/images/icons/macos/whatsapp.webp",
  imessage: "/images/icons/macos/imessage.webp",
  slack: "/images/icons/macos/slack.webp",
  discord: "/images/icons/macos/discord.webp",
};

export const BOT_AUTH_COMMAND = "/auth";

export function isBotPlatform(value: string): value is BotPlatform {
  return (BOT_PLATFORMS as readonly string[]).includes(value);
}
