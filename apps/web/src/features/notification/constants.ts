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
