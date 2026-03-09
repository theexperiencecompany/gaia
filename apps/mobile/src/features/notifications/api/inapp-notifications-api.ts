import { apiService } from "@/lib/api";
import type {
  InAppNotificationStatus,
  InAppNotificationsListResponse,
  NotificationActionResponse,
  PlatformLinksResponse,
} from "../types/inapp-notification-types";

export const BULK_NOTIFICATION_ACTION = {
  MARK_READ: "mark_read",
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
};
