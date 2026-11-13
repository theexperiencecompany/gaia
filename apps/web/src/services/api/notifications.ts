import type { NotificationPlatform } from "@/features/notification/constants";
import { api } from "@/lib/api/typed";
import {
  type BulkActionRequest,
  BulkActions,
  type UseNotificationsOptions,
} from "@/types/features/notificationTypes";

/**
 * The notifications endpoints.
 *
 * Every response shape comes from the schema, so a body that is not the API's
 * (a proxy error page, truncated JSON) fails loudly at parse time instead of
 * surfacing as a TypeError deep in a hook.
 */
export class NotificationsAPI {
  static getNotifications(options: UseNotificationsOptions = {}) {
    return api.get("/api/v1/notifications", {
      query: {
        status: options.status,
        limit: options.limit,
        offset: options.offset,
        channel_type: options.channel_type,
      },
    });
  }

  static getNotification(notificationId: string) {
    return api.get("/api/v1/notifications/{notification_id}", {
      path: { notification_id: notificationId },
    });
  }

  static executeAction(notificationId: string, actionId: string) {
    return api.post(
      "/api/v1/notifications/{notification_id}/actions/{action_id}/execute",
      { path: { notification_id: notificationId, action_id: actionId } },
    );
  }

  static markAsRead(notificationId: string) {
    return api.post("/api/v1/notifications/{notification_id}/read", {
      path: { notification_id: notificationId },
    });
  }

  /** Archive one notification (uses the bulk-actions endpoint). */
  static archiveNotification(notificationId: string) {
    return NotificationsAPI.bulkAction([notificationId], BulkActions.ARCHIVE);
  }

  static bulkMarkAsRead(notificationIds: string[]) {
    return NotificationsAPI.bulkAction(notificationIds, BulkActions.MARK_READ);
  }

  static bulkArchive(notificationIds: string[]) {
    return NotificationsAPI.bulkAction(notificationIds, BulkActions.ARCHIVE);
  }

  private static bulkAction(
    notificationIds: string[],
    action: BulkActionRequest["action"],
  ) {
    return api.post("/api/v1/notifications/bulk-actions", {
      body: { notification_ids: notificationIds, action },
    });
  }

  /**
   * Mark every delivered notification as read, server-side — not just the
   * caller's currently-loaded page.
   */
  static markAllAsRead(channelType?: string) {
    return api.post("/api/v1/notifications/mark-all-read", {
      query: { channel_type: channelType },
    });
  }

  /** Channel preferences (telegram, discord, whatsapp, slack). */
  static getChannelPreferences() {
    return api.get("/api/v1/notifications/preferences/channels");
  }

  static async updateChannelPreference(
    platform: NotificationPlatform,
    enabled: boolean,
  ): Promise<void> {
    await api.put("/api/v1/notifications/preferences/channels", {
      body: { [platform]: enabled },
    });
  }
}
