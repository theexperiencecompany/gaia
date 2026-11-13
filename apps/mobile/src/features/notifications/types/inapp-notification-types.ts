import type { InAppNotificationContent } from "@gaia/shared/types";

export type {
  ChannelPlatform,
  ChannelPreferences,
  InAppNotification,
  InAppNotificationContent,
  NotificationActionConfig as InAppNotificationActionConfig,
  NotificationActionStyle,
  NotificationActionType,
  NotificationStatus,
  PlatformLink,
  PlatformLinksResponse,
} from "@gaia/shared/types";
export {
  NotificationActionStyle as InAppNotificationActionStyle,
  NotificationActionType as InAppNotificationActionType,
  NotificationStatus as InAppNotificationStatus,
} from "@gaia/shared/types";

export type InAppNotificationAction = NonNullable<
  InAppNotificationContent["actions"]
>[number];

export interface InAppNotificationsListResponse {
  notifications: import("@gaia/shared/types").InAppNotification[];
  total: number;
  limit: number;
  offset: number;
}

// The legacy notification action endpoints' result; the API no longer publishes this model.
export interface NotificationActionResponse {
  success: boolean;
  message: string;
  data?: { redirect_url?: string; [key: string]: unknown } | null;
}

export interface NotificationCategoryPreferences {
  push: boolean;
  in_app: boolean;
}

export interface NotificationPreferences {
  global: NotificationCategoryPreferences;
  categories: Record<string, NotificationCategoryPreferences>;
}
