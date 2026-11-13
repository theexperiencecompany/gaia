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

export type NotificationPlatform = BotPlatform;

export const NOTIFICATION_PLATFORM_LABELS: Record<
  NotificationPlatform,
  string
> = BOT_PLATFORM_LABELS;

export const NOTIFICATION_PLATFORM_ICONS: Record<NotificationPlatform, string> =
  BOT_PLATFORM_ICONS;
