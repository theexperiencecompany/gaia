import { apiauth } from "@/lib/api";
import {
  type BulkActionRequest,
  BulkActions,
  type NotificationResponse,
  type PaginatedNotificationsResponse,
  type SnoozeRequest,
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

    return response.data;
  }

  /**
   * Fetch all notifications regardless of status
   */
  static async getAllNotifications(
    options: Omit<UseNotificationsOptions, "status"> = {},
  ): Promise<PaginatedNotificationsResponse> {
    const params = new URLSearchParams();

    if (options.limit) params.append("limit", options.limit.toString());
    if (options.offset) params.append("offset", options.offset.toString());
    if (options.channel_type)
      params.append("channel_type", options.channel_type);

    const response = await apiauth.get<PaginatedNotificationsResponse>(
      `${NotificationsAPI.BASE_URL}?${params.toString()}`,
    );

    return response.data;
  }

  /**
   * Fetch read notifications
   */
  static async getReadNotifications(
    options: Omit<UseNotificationsOptions, "status"> = {},
  ): Promise<PaginatedNotificationsResponse> {
    const params = new URLSearchParams();

    if (options.limit) params.append("limit", options.limit.toString());
    if (options.offset) params.append("offset", options.offset.toString());
    if (options.channel_type)
      params.append("channel_type", options.channel_type);

    const response = await apiauth.get<PaginatedNotificationsResponse>(
      `${NotificationsAPI.BASE_URL}/status?${params.toString()}`,
    );

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
   * Snooze a notification until a specific time
   */
  static async snoozeNotification(
    notificationId: string,
    snoozeUntil: Date,
  ): Promise<NotificationResponse> {
    const snoozeRequest: SnoozeRequest = {
      snooze_until: snoozeUntil.toISOString(),
    };

    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/${notificationId}/snooze`,
      snoozeRequest,
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
   * Delete notifications permanently
   */
  static async bulkDelete(
    notificationIds: string[],
  ): Promise<NotificationResponse> {
    const bulkRequest: BulkActionRequest = {
      notification_ids: notificationIds,
      action: BulkActions.DELETE,
    };

    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/bulk-actions`,
      bulkRequest,
    );
    return response.data;
  }

  /**
   * Get unread notification count
   */
  static async getUnreadCount(): Promise<{ count: number }> {
    const response = await apiauth.get<{ count: number }>(
      `${NotificationsAPI.BASE_URL}/unread/count`,
    );
    return response.data;
  }

  /**
   * Create a test notification for debugging WebSocket
   */
  static async createTestNotification(
    type: string = "all",
  ): Promise<NotificationResponse> {
    const params = new URLSearchParams();
    if (type !== "all") {
      params.append("notification_type", type);
    }

    const response = await apiauth.post<NotificationResponse>(
      `${NotificationsAPI.BASE_URL}/test?${params.toString()}`,
    );
    return response.data;
  }
}
