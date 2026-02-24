export const NOTIFICATION_PLATFORMS = ["telegram", "discord"] as const;

type NotificationPlatform = (typeof NOTIFICATION_PLATFORMS)[number];

export const NOTIFICATION_PLATFORM_LABELS: Record<
  NotificationPlatform,
  string
> = {
  telegram: "Telegram",
  discord: "Discord",
};

const NOTIFICATION_PLATFORMS_SET = new Set<string>(
  NOTIFICATION_PLATFORMS,
);
