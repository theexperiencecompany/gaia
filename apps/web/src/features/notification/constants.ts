export const NOTIFICATION_PLATFORMS = [
  "telegram",
  "discord",
  "whatsapp",
  "slack",
] as const;

export type NotificationPlatform = (typeof NOTIFICATION_PLATFORMS)[number];

export const NOTIFICATION_PLATFORM_LABELS: Record<
  NotificationPlatform,
  string
> = {
  telegram: "Telegram",
  discord: "Discord",
  whatsapp: "WhatsApp",
  slack: "Slack",
};

export const NOTIFICATION_PLATFORM_ICONS: Record<NotificationPlatform, string> =
  {
    telegram: "/images/icons/macos/telegram.webp",
    discord: "/images/icons/macos/discord.webp",
    whatsapp: "/images/icons/macos/whatsapp.webp",
    slack: "/images/icons/macos/slack.webp",
  };
