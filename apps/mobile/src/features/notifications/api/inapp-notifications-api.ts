import { apiService } from "@/lib/api";
import type {
  InAppNotificationStatus,
  InAppNotificationsListResponse,
  NotificationActionResponse,
  NotificationPreferences,
  PlatformLinksResponse,
} from "../types/inapp-notification-types";

export const BULK_NOTIFICATION_ACTION = {
  MARK_READ: "mark_read",
  ARCHIVE: "archive",
  DELETE: "delete",
} as const;

type BulkNotificationActionType =
  (typeof BULK_NOTIFICATION_ACTION)[keyof typeof BULK_NOTIFICATION_ACTION];

interface BulkActionsPayload {
  notification_ids: string[];
  action: BulkNotificationActionType;
}

interface GetNotificationsParams {
  status?: InAppNotificationStatus;
  limit?: number;
  offset?: number;
}

interface SnoozePayload {
  snooze_until: string;
}

function toQueryString(params?: GetNotificationsParams): string {
  if (!params) {
    return "";
  }

  const searchParams = new URLSearchParams();

  if (params.status) {
    searchParams.set("status", params.status);
  }

  if (typeof params.limit === "number") {
    searchParams.set("limit", String(params.limit));
  }

  if (typeof params.offset === "number") {
    searchParams.set("offset", String(params.offset));
  }

  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export const inAppNotificationsApi = {
  getNotifications: async (
    params?: GetNotificationsParams,
  ): Promise<InAppNotificationsListResponse> => {
    return apiService.get<InAppNotificationsListResponse>(
      `/notifications${toQueryString(params)}`,
    );
  },

  markAsRead: async (
    notificationId: string,
  ): Promise<NotificationActionResponse> => {
    return apiService.post<NotificationActionResponse>(
      `/notifications/${notificationId}/read`,
    );
  },

  bulkMarkAsRead: async (
    notificationIds: string[],
  ): Promise<NotificationActionResponse> => {
    const payload: BulkActionsPayload = {
      notification_ids: notificationIds,
      action: BULK_NOTIFICATION_ACTION.MARK_READ,
    };

    return apiService.post<NotificationActionResponse>(
      "/notifications/bulk-actions",
      payload,
    );
  },

  executeAction: async (
    notificationId: string,
    actionId: string,
  ): Promise<NotificationActionResponse> => {
    return apiService.post<NotificationActionResponse>(
      `/notifications/${notificationId}/actions/${actionId}/execute`,
    );
  },

  getPlatformLinks: async (): Promise<PlatformLinksResponse> => {
    return apiService.get<PlatformLinksResponse>("/platform-links");
  },

  snoozeNotification: async (
    notificationId: string,
    snoozeUntil: Date,
  ): Promise<NotificationActionResponse> => {
    const payload: SnoozePayload = {
      snooze_until: snoozeUntil.toISOString(),
    };
    return apiService.post<NotificationActionResponse>(
      `/notifications/${notificationId}/snooze`,
      payload,
    );
  },

  archiveNotification: async (
    notificationId: string,
  ): Promise<NotificationActionResponse> => {
    return apiService.post<NotificationActionResponse>(
      `/notifications/${notificationId}/archive`,
    );
  },

  deleteNotification: async (
    notificationId: string,
  ): Promise<NotificationActionResponse> => {
    return apiService.delete<NotificationActionResponse>(
      `/notifications/${notificationId}`,
    );
  },

  markAllAsRead: async (): Promise<NotificationActionResponse> => {
    return apiService.post<NotificationActionResponse>(
      "/notifications/mark-all-read",
    );
  },

  bulkMarkRead: async (
    notificationIds: string[],
  ): Promise<NotificationActionResponse> => {
    const payload: BulkActionsPayload = {
      notification_ids: notificationIds,
      action: BULK_NOTIFICATION_ACTION.MARK_READ,
    };
    return apiService.post<NotificationActionResponse>(
      "/notifications/bulk-actions",
      payload,
    );
  },

  bulkArchive: async (
    notificationIds: string[],
  ): Promise<NotificationActionResponse> => {
    const payload: BulkActionsPayload = {
      notification_ids: notificationIds,
      action: BULK_NOTIFICATION_ACTION.ARCHIVE,
    };
    return apiService.post<NotificationActionResponse>(
      "/notifications/bulk-actions",
      payload,
    );
  },

  bulkDelete: async (
    notificationIds: string[],
  ): Promise<NotificationActionResponse> => {
    const payload: BulkActionsPayload = {
      notification_ids: notificationIds,
      action: BULK_NOTIFICATION_ACTION.DELETE,
    };
    return apiService.post<NotificationActionResponse>(
      "/notifications/bulk-actions",
      payload,
    );
  },

  getNotificationPreferences: async (): Promise<NotificationPreferences> => {
    return apiService.get<NotificationPreferences>(
      "/notifications/preferences",
    );
  },

  updateNotificationPreferences: async (
    prefs: Partial<NotificationPreferences>,
  ): Promise<NotificationActionResponse> => {
    return apiService.put<NotificationActionResponse>(
      "/notifications/preferences",
      prefs,
    );
  },
};
