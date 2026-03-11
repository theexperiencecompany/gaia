export type {
  InAppNotification,
  InAppNotificationContent,
  NotificationAction as InAppNotificationAction,
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
