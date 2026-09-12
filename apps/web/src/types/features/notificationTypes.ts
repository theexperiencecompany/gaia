import type { Schema } from "@shared/api/generated";
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

export type RedirectConfig = Schema<"RedirectConfig">;

export type ApiCallConfig = Schema<"ApiCallConfig">;

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

export type ModalConfig = Schema<"ModalConfig">;

export type NotificationAction = Schema<"NotificationActionView">;

export type NotificationContent = Schema<"NotificationContent">;

export interface NotificationMetadata {
  // Source tracking
  source?: "system" | "user" | "integration" | "workflow";
  source_id?: string;

  // Entity relationships
  reminder_id?: string;
  todo_id?: string;
  calendar_event_id?: string;
  email_id?: string;
  project_id?: string;

  // Context information
  trigger_event?: string;
  user_action?: string;
  integration_name?: string;

  // Delivery tracking
  delivery_attempts?: number;
  last_attempt_at?: string;
  failure_reason?: string;

  // Grouping and categorization
  category?: string;
  tags?: string[];
  group_key?: string;

  // Custom tracking
  analytics?: {
    campaign_id?: string;
    utm_source?: string;
    utm_medium?: string;
    utm_campaign?: string;
  };

  // Timestamps
  created_at?: string;
  updated_at?: string;

  // Allow for additional custom fields
  [key: string]: string | number | boolean | string[] | object | undefined;
}

export type NotificationView = Schema<"NotificationView">;

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

export interface NotificationUpdate {
  // Status changes
  status?: SharedNotificationStatus;
  read_at?: string;
  archived_at?: string;
  snoozed_until?: string;

  // Content updates
  content?: Partial<NotificationContent>;

  // Action updates
  disable_actions?: string[]; // Action IDs to disable
  add_actions?: NotificationAction[];

  // Visual updates
  highlight?: boolean;
  badge_count?: number;

  // Metadata updates
  metadata?: Partial<NotificationMetadata>;

  // Expiration
  expires_at?: string;
  auto_archive_after?: number; // minutes
}

export interface ActionResult {
  success: boolean;
  message?: string;
  data?: ActionResultData;
  next_actions?: NotificationAction[];
  update_notification?: NotificationUpdate;
  error_code?: string;
}

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

// API Request/Response types

export type BulkActionRequest = Schema<"BulkActionRequest">;

export interface NotificationResponse {
  success: boolean;
  message: string;
  data?: ActionResultData | NotificationView; // Allow both types
}

export type PaginatedNotificationsResponse =
  Schema<"PaginatedNotificationsResponse">;

// Hook options
export interface UseNotificationsOptions {
  status?: SharedNotificationStatus;
  limit?: number;
  offset?: number;
  channel_type?: string;
}
