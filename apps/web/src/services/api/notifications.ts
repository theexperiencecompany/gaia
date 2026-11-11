import type { ChannelPlatform } from "@gaia/shared/types";
import { ApiError } from "@shared/api";
import type {
  BriefDeliveryWorkflow,
  BriefDeliveryWorkflowsConflict,
  BriefingScheduleUpdate,
} from "@shared/api/generated";
import { z } from "zod";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
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

  /** The enabled state of every user-configurable notification channel. */
  static getChannelPreferences() {
    return api.get("/api/v1/notifications/preferences/channels");
  }

  /** How often briefs come, and the daily brief's hour on the user's clock. */
  static getBriefingSchedule() {
    return api.get("/api/v1/notifications/preferences/briefing-schedule");
  }

  /** Silent so a refused "off" can open its own dialog instead of a toast. */
  static updateBriefingSchedule(update: BriefingScheduleUpdate) {
    return api.put("/api/v1/notifications/preferences/briefing-schedule", {
      body: update,
      silent: true,
    });
  }

  static async updateChannelPreference(
    channel: ChannelPlatform,
    enabled: boolean,
  ): Promise<void> {
    await api.put("/api/v1/notifications/preferences/channels", {
      body: { [channel]: enabled },
    });
  }
}

const BriefDeliveryWorkflowsSchema = z.array(
  z.object({
    id: z.string(),
    title: z.string(),
  }) satisfies z.ZodType<BriefDeliveryWorkflow>,
);

/** A refused "off": the API's own words and the workflows still delivering to the brief. */
export type BriefsOffBlock = Pick<
  BriefDeliveryWorkflowsConflict,
  "message" | "workflows"
>;

/** What blocked turning briefs off, when that is why the save failed, else null. */
export function readBriefsOffBlock(error: unknown): BriefsOffBlock | null {
  if (
    !(error instanceof ApiError) ||
    error.code !== API_ERROR_CODES.BRIEF_DELIVERY_WORKFLOWS_EXIST
  ) {
    return null;
  }
  return {
    message: error.message,
    workflows: BriefDeliveryWorkflowsSchema.parse(error.envelope?.workflows),
  };
}
