import type { NotificationPlatform } from "@/features/notification/constants";
import { apiauth } from "@/lib/api/client";
import {
  type BulkActionRequest,
  BulkActions,
  type NotificationResponse,
  type PaginatedNotificationsResponse,
  type UseNotificationsOptions,
} from "@/types/features/notificationTypes";

export class NotificationsAPI {
  private static BASE_URL = "/notifications";

  /**
   * Fetch notifications with optional filters
   */
  static async getNotifications(
    options: UseNotificationsOptions = {},
  ): Promise<PaginatedNotificationsResponse> {
    const params = new URLSearchParams();

    if (options.status) params.append("status", options.status);
    if (options.limit) params.append("limit", options.limit.toString());
    if (options.offset) params.append("offset", options.offset.toString());
    if (options.channel_type)
      params.append("channel_type", options.channel_type);

    const response = await apiauth.get<PaginatedNotificationsResponse>(
      `${NotificationsAPI.BASE_URL}?${params.toString()}`,
    );

    // The endpoint always returns a `notifications` array. Anything else means
    // the body did not come from the API (proxy/edge error page parsed as the
    // response, truncated JSON, …) — fail loudly here rather than letting an
    // undefined leak into the store and surface as a TypeError deep in a hook.
    if (!Array.isArray(response.data?.notifications)) {
      throw new Error(
        "Malformed notifications response: expected `notifications` to be an array",
      );
    }

    return response.data;
  }

  /**
   * Get a single notification by ID
   */
  static async getNotification(
    notificationId: string,
  ): Promise<NotificationResponse> {
    const response = await apiauth.get<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/${notificationId}`,
    );
    return response.data;
  }

  /**
   * Execute a notification action
   */
  static async executeAction(
    notificationId: string,
    actionId: string,
  ): Promise<NotificationResponse> {
    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/${notificationId}/actions/${actionId}/execute`,
    );
    return response.data;
  }

  /**
   * Mark a single notification as read
   */
  static async markAsRead(
    notificationId: string,
  ): Promise<NotificationResponse> {
    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/${notificationId}/read`,
    );
    return response.data;
  }

  /**
   * Archive a notification (uses bulk actions endpoint)
   */
  static async archiveNotification(
    notificationId: string,
  ): Promise<NotificationResponse> {
    const bulkRequest: BulkActionRequest = {
      notification_ids: [notificationId],
      action: BulkActions.ARCHIVE,
    };

    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/bulk-actions`,
      bulkRequest,
    );
    return response.data;
  }

  /**
   * Bulk mark notifications as read
   */
  static async bulkMarkAsRead(
    notificationIds: string[],
  ): Promise<NotificationResponse> {
    const bulkRequest: BulkActionRequest = {
      notification_ids: notificationIds,
      action: BulkActions.MARK_READ,
    };

    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/bulk-actions`,
      bulkRequest,
    );
    return response.data;
  }

  /**
   * Bulk archive notifications
   */
  static async bulkArchive(
    notificationIds: string[],
  ): Promise<NotificationResponse> {
    const bulkRequest: BulkActionRequest = {
      notification_ids: notificationIds,
      action: BulkActions.ARCHIVE,
    };

    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/bulk-actions`,
      bulkRequest,
    );
    return response.data;
  }

  /**
   * Get notification channel preferences (telegram, discord, whatsapp, slack)
   */
  static async getChannelPreferences(): Promise<
    Record<NotificationPlatform, boolean>
  > {
    const response = await apiauth.get<Record<NotificationPlatform, boolean>>(
      `${NotificationsAPI.BASE_URL}/preferences/channels`,
    );
    return response.data;
  }

  /**
   * Update a notification channel preference
   */
  static async updateChannelPreference(
    platform: NotificationPlatform,
    enabled: boolean,
  ): Promise<void> {
    await apiauth.put(`${NotificationsAPI.BASE_URL}/preferences/channels`, {
      [platform]: enabled,
    });
  }
}
