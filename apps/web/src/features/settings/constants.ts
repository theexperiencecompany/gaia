import type { BotPlatform } from "@/config/botPlatforms";

/** Where chat apps are connected, managed and disconnected. */
export const LINKED_ACCOUNTS_SETTINGS_PATH = "/settings/linked-accounts";

/** Where every channel GAIA reaches you on is switched on or off. */
export const NOTIFICATIONS_SETTINGS_PATH = "/settings/notifications";

interface LinkedPlatformDetails {
  description: string;
  connectedDescription: string;
  premium?: boolean;
  requiresPhone?: boolean;
  /** The linked account has a DM chat the web app can open. */
  chat?: boolean;
}

export const LINKED_PLATFORM_DETAILS: Record<
  BotPlatform,
  LinkedPlatformDetails
> = {
  telegram: {
    description: "Chat with GAIA on Telegram",
    connectedDescription: "Message your bot on Telegram to chat with GAIA",
    chat: true,
  },
  whatsapp: {
    description: "Connect GAIA to WhatsApp (Beta)",
    connectedDescription: "Message GAIA on WhatsApp",
    chat: true,
  },
  imessage: {
    description: "Text GAIA over iMessage (Pro)",
    connectedDescription: "Message GAIA from your iPhone or Mac",
    premium: true,
    requiresPhone: true,
    chat: true,
  },
  slack: {
    description: "Bring GAIA into your Slack workspace",
    connectedDescription: "Use /gaia in Slack to chat with GAIA",
  },
  discord: {
    description: "Use GAIA directly from Discord servers and DMs",
    connectedDescription: "Use /gaia in Discord to chat with GAIA",
  },
};
