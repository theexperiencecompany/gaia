import type {
  ChannelPreferences,
  NotificationActionView,
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

export interface NotificationActionConfig {
  redirect?: {
    url: string;
    open_in_new_tab?: boolean;
    close_notification?: boolean;
  };
  api_call?: {
    endpoint: string;
    method?: "GET" | "POST" | "PUT" | "DELETE";
    payload?: Record<string, unknown>;
  };
  workflow?: {
    workflow_id: string;
    parameters?: Record<string, unknown>;
  };
  modal?: {
    component: string;
    props?: Record<string, unknown>;
  };
}

export type NotificationAction = NotificationActionView;

export interface InAppNotificationContent {
  title: string;
  body: string;
  actions?: NotificationAction[];
}

export interface InAppNotification {
  id: string;
  status: NotificationStatus;
  source?: string;
  type?: string;
  created_at: string;
  read_at?: string | null;
  content: InAppNotificationContent;
}

export interface PlatformLink {
  platform: string;
  platformUserId: string;
  username?: string;
  displayName?: string;
  connectedAt?: string;
}

export interface PlatformLinksResponse {
  platform_links: Record<string, PlatformLink>;
}

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
