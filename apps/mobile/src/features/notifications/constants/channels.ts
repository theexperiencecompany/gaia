import { EMAIL_CHANNEL_DESCRIPTION } from "@gaia/shared";
import type { ChannelPlatform } from "@gaia/shared/types";
import type { AnyIcon } from "@/components/icons";
import {
  DiscordIcon,
  Mail01Icon,
  Message01Icon,
  SlackIcon,
  TelegramIcon,
  WhatsappIcon,
} from "@/components/icons";

export interface NotificationChannelMeta {
  name: string;
  description: string;
  icon: AnyIcon;
  iconColor: string;
  iconBg: string;
  /**
   * Bot channels deliver only to a linked account; email reaches the user
   * through the address on their GAIA account.
   */
  requiresLink: boolean;
}

/**
 * Display data for every channel in the shared `NOTIFICATION_CHANNELS`. Keyed by
 * `ChannelPlatform`, so a channel added there fails type-check here until it
 * has a row.
 */
export const NOTIFICATION_CHANNEL_META: Record<
  ChannelPlatform,
  NotificationChannelMeta
> = {
  telegram: {
    name: "Telegram",
    description: "Receive alerts via your connected Telegram bot",
    icon: TelegramIcon,
    iconColor: "#2AABEE",
    iconBg: "rgba(42,171,238,0.15)",
    requiresLink: true,
  },
  discord: {
    name: "Discord",
    description: "Receive alerts via your connected Discord bot",
    icon: DiscordIcon,
    iconColor: "#5865F2",
    iconBg: "rgba(88,101,242,0.15)",
    requiresLink: true,
  },
  whatsapp: {
    name: "WhatsApp",
    description: "Receive alerts via your connected WhatsApp bot",
    icon: WhatsappIcon,
    iconColor: "#25D366",
    iconBg: "rgba(37,211,102,0.15)",
    requiresLink: true,
  },
  slack: {
    name: "Slack",
    description: "Receive alerts via your connected Slack workspace",
    icon: SlackIcon,
    iconColor: "#E01E5A",
    iconBg: "rgba(224,30,90,0.15)",
    requiresLink: true,
  },
  imessage: {
    name: "iMessage",
    description: "Receive alerts via your connected iMessage",
    icon: Message01Icon,
    iconColor: "#34C759",
    iconBg: "rgba(52,199,89,0.15)",
    requiresLink: true,
  },
  email: {
    name: "Email",
    description: EMAIL_CHANNEL_DESCRIPTION,
    icon: Mail01Icon,
    iconColor: "#00bbff",
    iconBg: "rgba(0,187,255,0.15)",
    requiresLink: false,
  },
};
