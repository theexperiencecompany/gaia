export const NOTIFICATION_PLATFORMS = [
  "telegram",
  "discord",
  "whatsapp",
] as const;

export type NotificationPlatform = (typeof NOTIFICATION_PLATFORMS)[number];

export const NOTIFICATION_PLATFORM_LABELS: Record<
  NotificationPlatform,
  string
> = {
  telegram: "Telegram",
  discord: "Discord",
  whatsapp: "WhatsApp",
};

export const NOTIFICATION_PLATFORMS_SET = new Set<string>(
  NOTIFICATION_PLATFORMS,
);
