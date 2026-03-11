/**
 * Shared notifications API contract.
 * Defines endpoint constants and parameter interfaces used by all platforms.
 * Each platform implements the actual HTTP calls using its own HTTP client.
 */

export const NOTIFICATION_ENDPOINTS = {
  list: "/notifications",
  get: (notificationId: string) => `/notifications/${notificationId}`,
  markAsRead: (notificationId: string) => `/notifications/${notificationId}/read`,
  snooze: (notificationId: string) => `/notifications/${notificationId}/snooze`,
  executeAction: (notificationId: string, actionId: string) =>
    `/notifications/${notificationId}/actions/${actionId}/execute`,
  bulkActions: "/notifications/bulk-actions",
  readStatus: "/notifications/status",
  unreadCount: "/notifications/unread/count",
  channelPreferences: "/notifications/preferences/channels",
  test: "/notifications/test",
} as const;

export type NotificationStatusFilter =
  | "pending"
  | "delivered"
  | "read"
  | "snoozed"
  | "archived";

export interface NotificationListParams {
  status?: NotificationStatusFilter;
  limit?: number;
  offset?: number;
  channel_type?: string;
}

export interface NotificationReadStatusParams {
  limit?: number;
  offset?: number;
  channel_type?: string;
}

export type BulkNotificationAction = "mark_read" | "archive" | "delete";

export interface BulkNotificationActionParams {
  notification_ids: string[];
  action: BulkNotificationAction;
}

export interface SnoozeNotificationParams {
  snooze_until: string;
}

export interface UpdateChannelPreferenceParams {
  telegram?: boolean;
  discord?: boolean;
}

export interface TestNotificationParams {
  notification_type?: string;
}
