import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  BOT_PLATFORMS,
  type BotPlatform,
} from "@/config/botPlatforms";

export const NOTIFICATION_PLATFORMS = BOT_PLATFORMS;

export type NotificationPlatform = BotPlatform;

export const NOTIFICATION_PLATFORM_LABELS: Record<
  NotificationPlatform,
  string
> = BOT_PLATFORM_LABELS;

export const NOTIFICATION_PLATFORM_ICONS: Record<NotificationPlatform, string> =
  BOT_PLATFORM_ICONS;

// Channel-level maps extend the platform maps with the always-available
// in-app channel, which is delivered over WebSocket rather than a bot.
export const NOTIFICATION_CHANNEL_LABELS: Record<string, string> = {
  ...NOTIFICATION_PLATFORM_LABELS,
  inapp: "In-app",
};

export const NOTIFICATION_CHANNEL_ICONS: Record<string, string> = {
  ...NOTIFICATION_PLATFORM_ICONS,
  inapp: "/images/logos/macos.webp",
};
