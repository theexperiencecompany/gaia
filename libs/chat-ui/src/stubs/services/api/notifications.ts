/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type {
  NotificationResponse,
  PaginatedNotificationsResponse,
  UseNotificationsOptions,
} from "@/types/features/notificationTypes";

const emptyPaginated = (): PaginatedNotificationsResponse =>
  ({}) as PaginatedNotificationsResponse;

const emptyResponse = (): NotificationResponse => ({}) as NotificationResponse;

export class NotificationsAPI {
  static async getNotifications(
    _options: UseNotificationsOptions = {},
  ): Promise<PaginatedNotificationsResponse> {
    return emptyPaginated();
  }

  static async getAllNotifications(
    _options: Omit<UseNotificationsOptions, "status"> = {},
  ): Promise<PaginatedNotificationsResponse> {
    return emptyPaginated();
  }

  static async getReadNotifications(
    _options: Omit<UseNotificationsOptions, "status"> = {},
  ): Promise<PaginatedNotificationsResponse> {
    return emptyPaginated();
  }

  static async getNotification(
    _notificationId: string,
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async executeAction(
    _notificationId: string,
    _actionId: string,
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async markAsRead(
    _notificationId: string,
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async archiveNotification(
    _notificationId: string,
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async snoozeNotification(
    _notificationId: string,
    _snoozeUntil: Date,
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async bulkMarkAsRead(
    _notificationIds: string[],
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async bulkArchive(
    _notificationIds: string[],
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async bulkDelete(
    _notificationIds: string[],
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }

  static async getUnreadCount(): Promise<{ count: number }> {
    return { count: 0 };
  }

  static async getChannelPreferences(): Promise<{
    telegram: boolean;
    discord: boolean;
    whatsapp: boolean;
  }> {
    return { telegram: false, discord: false, whatsapp: false };
  }

  static async updateChannelPreference(
    _platform: "telegram" | "discord" | "whatsapp",
    _enabled: boolean,
  ): Promise<void> {}

  static async createTestNotification(
    _type: string = "all",
  ): Promise<NotificationResponse> {
    return emptyResponse();
  }
}
