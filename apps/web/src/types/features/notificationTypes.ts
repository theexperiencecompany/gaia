import type {
  ActionExecutionResponse,
  NotificationActionView,
} from "@shared/api/generated";

export type {
  ApiCallConfig,
  BulkActionRequest,
  ModalConfig,
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

export interface ModalProps {
  // Base modal props
  open?: boolean;
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  onClose?: () => void;

  // Entity data
  todoId?: string;
  emailId?: string;
  email_id?: string; // Alternative naming for email ID
  calendarEventId?: string;
  noteId?: string;

  // Action contexts
  mode?: "create" | "edit" | "view" | "delete";
  defaultValues?: Record<string, string | number | boolean>;
  actionId?: string; // Action ID for tracking which action triggered the modal
  notificationId?: string; // Notification ID for tracking which notification triggered the modal

  // Email-specific props for EmailPreviewModal
  subject?: string;
  body?: string;
  recipients?: string[];

  // Component-specific data
  todo?: {
    id: string;
    title: string;
    description?: string;
    priority: "high" | "medium" | "low";
    due_date?: string;
    project_id?: string;
  };

  email?: {
    id: string;
    subject: string;
    to: string[];
    body?: string;
    attachments?: Array<{ name: string; url: string }>;
  };

  calendar?: {
    id: string;
    title: string;
    start: string;
    end: string;
    description?: string;
    location?: string;
  };
}

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
export type NotificationActionResult = Omit<ActionExecutionResponse, "data"> & {
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
