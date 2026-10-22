import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  BOT_PLATFORMS,
  type BotPlatform,
} from "@/config/botPlatforms";

// One canonical query holds the unfiltered page every consumer reads, so the
// fetch size must be fixed. 100 is the API's own ceiling (`le=100` on the limit
// query param) — asking for more is a 422, not a bigger page.
export const NOTIFICATION_PAGE_SIZE = 100;

export const NOTIFICATION_PLATFORMS = BOT_PLATFORMS;

// The weekly recap's notification kind (NOTIFICATION_KIND_BRIEFING_WEEKLY in the API).
export const NOTIFICATION_KIND_BRIEFING_WEEKLY = "briefing_weekly";

export type NotificationPlatform = BotPlatform;

export const NOTIFICATION_PLATFORM_LABELS: Record<
  NotificationPlatform,
  string
> = BOT_PLATFORM_LABELS;

export const NOTIFICATION_PLATFORM_ICONS: Record<NotificationPlatform, string> =
  BOT_PLATFORM_ICONS;

// Channel-level maps extend the platform maps with the channels that are not bot
// platforms: the always-available in-app channel (delivered over WebSocket) and
// email (delivered to the account address).
export const NOTIFICATION_CHANNEL_LABELS: Record<string, string> = {
  ...NOTIFICATION_PLATFORM_LABELS,
  inapp: "In-app",
  email: "Email",
};

export const NOTIFICATION_CHANNEL_ICONS: Record<string, string> = {
  ...NOTIFICATION_PLATFORM_ICONS,
  inapp: "/images/logos/macos.webp",
  email: "/images/icons/macos/mail.webp",
};
