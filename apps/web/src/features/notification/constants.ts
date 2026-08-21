import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  BOT_PLATFORMS,
  type BotPlatform,
} from "@/config/botPlatforms";

// The shared notification store holds one unfiltered page for every consumer,
// so the fetch must be canonical. 100 is the API's own ceiling (`le=100` on the
// limit query param) — asking for more is a 422, not a bigger page.
export const NOTIFICATION_PAGE_SIZE = 100;

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
