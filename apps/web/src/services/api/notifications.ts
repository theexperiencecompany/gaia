import type { NotificationPlatform } from "@/features/notification/constants";
import { apiauth } from "@/lib/api/client";
import {
  type BulkActionRequest,
  BulkActions,
  type NotificationResponse,
  type PaginatedNotificationsResponse,
  type UseNotificationsOptions,
} from "@/types/features/notificationTypes";

/** Shape-only description of an unexpected payload — never its contents. */
function describePayload(payload: unknown): string {
  if (typeof payload === "string") {
    // Classify by the first non-whitespace character rather than quoting the
    // body. This still separates the cases that matter — an edge/proxy HTML
    // page from truncated JSON from an empty body — without putting any of the
    // response's bytes into the error, which could carry a token or user text.
    const firstChar = payload.trimStart()[0];
    const kind =
      firstChar === "<"
        ? " that looks like markup"
        : firstChar === "{" || firstChar === "["
          ? " that looks like truncated JSON"
          : "";
    return `a ${payload.length}-char string${kind}`;
  }
  if (payload === null || payload === undefined) return String(payload);
  if (Array.isArray(payload)) return `an array of ${payload.length}`;
  if (typeof payload === "object") {
    return `an object with keys [${Object.keys(payload).join(", ")}]`;
  }
  return `a ${typeof payload}`;
}

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

    // The endpoint always returns a `notifications` array (required field on the
    // API's response model). Anything else means the body did not come from the
    // API — a proxy/edge error page or truncated JSON that axios silently leaves
    // as a string. Fail loudly, and describe what actually arrived, so the next
    // occurrence identifies itself instead of surfacing as a TypeError deep in a
    // hook. Only the status and the payload's shape are reported, never its
    // contents, so this stays free of notification text.
    if (!Array.isArray(response.data?.notifications)) {
      throw new Error(
        `Malformed notifications response: expected \`notifications\` to be an array. ` +
          `HTTP ${response.status}, content-type ${response.headers["content-type"] ?? "none"}, ` +
          `received ${describePayload(response.data)}`,
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
