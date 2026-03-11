export {
  NotificationStatus as InAppNotificationStatus,
  NotificationActionType as InAppNotificationActionType,
  NotificationActionStyle as InAppNotificationActionStyle,
} from "@gaia/shared/types";

export type {
  NotificationStatus,
  NotificationActionType,
  NotificationActionStyle,
  NotificationActionConfig as InAppNotificationActionConfig,
  NotificationAction as InAppNotificationAction,
  InAppNotificationContent,
  InAppNotification,
  PlatformLink,
  PlatformLinksResponse,
} from "@gaia/shared/types";

export interface InAppNotificationsListResponse {
  notifications: import("@gaia/shared/types").InAppNotification[];
  total: number;
  limit: number;
  offset: number;
}

export interface NotificationActionResponse {
  success: boolean;
  message: string;
  data?: {
    redirect_url?: string;
    [key: string]: unknown;
  };
}

export interface NotificationCategoryPreferences {
  push: boolean;
  email: boolean;
  in_app: boolean;
}

export interface NotificationPreferences {
  global: NotificationCategoryPreferences;
  categories: Record<string, NotificationCategoryPreferences>;
}
