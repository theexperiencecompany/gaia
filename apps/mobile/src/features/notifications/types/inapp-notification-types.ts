import type { ActionExecutionResponse } from "@gaia/shared/api/generated";

export type {
  ChannelPlatform,
  ChannelPreferences,
  InAppNotification,
  InAppNotificationContent,
  NotificationAction as InAppNotificationAction,
  NotificationActionConfig as InAppNotificationActionConfig,
  NotificationActionStyle,
  NotificationActionType,
  NotificationStatus,
  PlatformLink,
  PlatformLinksResponse,
  QuietHours,
} from "@gaia/shared/types";
export {
  NotificationActionStyle as InAppNotificationActionStyle,
  NotificationActionType as InAppNotificationActionType,
  NotificationStatus as InAppNotificationStatus,
} from "@gaia/shared/types";

export interface InAppNotificationsListResponse {
  notifications: import("@gaia/shared/types").InAppNotification[];
  total: number;
  limit: number;
  offset: number;
}

// The API's action result, with `data` narrowed to the redirect an action may carry.
export type NotificationActionResponse = Omit<
  ActionExecutionResponse,
  "data"
> & {
  data?: { redirect_url?: string; [key: string]: unknown } | null;
};

export interface NotificationCategoryPreferences {
  push: boolean;
  in_app: boolean;
}

export interface NotificationPreferences {
  global: NotificationCategoryPreferences;
  categories: Record<string, NotificationCategoryPreferences>;
  quiet_hours?: import("@gaia/shared/types").QuietHours | null;
}
