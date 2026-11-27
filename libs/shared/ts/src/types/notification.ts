import type {
  ActionConfig,
  ChannelPreferences,
  GetPlatformLinksResponse,
  NotificationActionView,
  NotificationContentView,
  PlatformLinkEntry,
} from "../api/generated";

export type {
  BriefingFrequency,
  BriefingScheduleState,
  ChannelPreferences,
} from "../api/generated";
export enum NotificationStatus {
  PENDING = "pending",
  DELIVERED = "delivered",
  READ = "read",
  ARCHIVED = "archived",
}

export enum NotificationActionType {
  REDIRECT = "redirect",
  API_CALL = "api_call",
  WORKFLOW = "workflow",
  MODAL = "modal",
}

export enum NotificationActionStyle {
  PRIMARY = "primary",
  SECONDARY = "secondary",
  DANGER = "danger",
}

export type NotificationActionConfig = ActionConfig;

export type NotificationAction = NotificationActionView;

export type InAppNotificationContent = NotificationContentView;

// Only mobile reads this: its notification normaliser fills the fields the
// API's NotificationView types as enums with free strings.
export interface InAppNotification {
  id: string;
  status: NotificationStatus;
  source?: string;
  type?: string;
  created_at: string;
  read_at?: string | null;
  content: InAppNotificationContent;
}

export type PlatformLink = PlatformLinkEntry;

export type PlatformLinksResponse = GetPlatformLinksResponse;

/**
 * Every channel the user can switch on or off: the API's ChannelPreferences
 * keys. `inapp` is absent on purpose; it is always delivered, so it has no
 * preference to store.
 */
export type ChannelPlatform = keyof ChannelPreferences;

// Keyed by ChannelPlatform, so a channel the API adds fails to compile until it is placed here.
const CHANNEL_DISPLAY_ORDER: Record<ChannelPlatform, true> = {
  telegram: true,
  discord: true,
  whatsapp: true,
  slack: true,
  imessage: true,
  email: true,
};

/** The switchable channels in the order settings list them. */
export const NOTIFICATION_CHANNELS = Object.keys(
  CHANNEL_DISPLAY_ORDER,
) as ChannelPlatform[];

// What the email switch controls: GAIA's own emails to the user (the brief, tips,
// check-ins), not a copy of every notification.
export const EMAIL_CHANNEL_DESCRIPTION =
  "Your brief, tips and check-ins by email";
