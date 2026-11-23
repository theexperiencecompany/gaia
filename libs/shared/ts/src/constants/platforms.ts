/**
 * The bot platforms GAIA supports, in the order pages offer them. Icons, copy
 * and demo content stay in the apps; this is only the set and the type, so a
 * new platform starts in one place instead of five unions.
 */

/** Display order: the onboarding pick first, then the install-your-own pair. */
export const BOT_PLATFORM_IDS = [
  "telegram",
  "whatsapp",
  "imessage",
  "slack",
  "discord",
] as const;

export type BotPlatform = (typeof BOT_PLATFORM_IDS)[number];
