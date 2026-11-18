import type {
  ActionExecutionResponse,
  NotificationActionView,
} from "@shared/api/generated";

export type {
  ApiCallConfig,
  BulkActionRequest,
  ModalConfig,
  NotificationContent,
  NotificationView,
  PaginatedNotificationsResponse,
  RedirectConfig,
} from "@shared/api/generated";

import type { NotificationStatus as SharedNotificationStatus } from "@shared/types";

export enum NotificationType {
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
  SUCCESS = "success",
}

// Re-export shared enum as the canonical NotificationStatus for web
export {
  NotificationActionStyle as ActionStyle,
  NotificationActionType as ActionType,
  NotificationStatus,
} from "@shared/types";

export type NotificationAction = NotificationActionView;

export interface ActionResultData {
  // Entity results
  created_entity?: {
    id: string;
    type: string;
    title?: string;
    url?: string;
  };

  updated_entity?: {
    id: string;
    field: string;
    old_value: string | number | boolean;
    new_value: string | number | boolean;
  };

  // Operation results
  affected_count?: number;
  processed_items?: string[];
  skipped_items?: Array<{
    id: string;
    reason: string;
  }>;

  // Redirect information
  redirect_url?: string;
  redirect_delay_ms?: number;

  // Follow-up actions
  suggested_actions?: Array<{
    label: string;
    action_id: string;
    description?: string;
  }>;

  // Status information
  status?: "completed" | "pending" | "failed" | "partial";
  progress?: {
    current: number;
    total: number;
    percentage: number;
  };
}

// The API's action result, with `data` narrowed to what an executed action carries.
export type ActionResult = Omit<ActionExecutionResponse, "data"> & {
  data?: ActionResultData | null;
};

export enum BulkActions {
  MARK_READ = "mark_read",
  ARCHIVE = "archive",
}

// Streamed by the send_notification agent tool — rendered as a chat tool card
export interface SendNotificationData {
  success: boolean;
  notification_id: string;
  title: string;
  message: string;
  notification_type: string;
  status: string;
  delivered_channels: string[];
}

// Hook options
export interface UseNotificationsOptions {
  status?: SharedNotificationStatus;
  limit?: number;
  offset?: number;
  channel_type?: string;
}
