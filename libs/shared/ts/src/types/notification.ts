import type { NotificationActionView } from "../api/generated";

export type { ChannelPreferences, QuietHours } from "../api/generated";
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

// Mirrors USER_CONFIGURABLE_CHANNELS in apps/api/app/constants/notifications.py:
// every channel the user can switch on or off. `inapp` is absent on purpose — it
// is always delivered, so it has no preference to store.
export const NOTIFICATION_CHANNELS = [
  "telegram",
  "discord",
  "whatsapp",
  "slack",
  "imessage",
  "email",
] as const;

export type ChannelPlatform = (typeof NOTIFICATION_CHANNELS)[number];

// What the email switch controls: GAIA's own emails to the user, not a copy of
// every notification (no notification is delivered by email).
export const EMAIL_CHANNEL_DESCRIPTION = "Tips and check-in emails from GAIA";
