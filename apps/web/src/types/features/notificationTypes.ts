import type { NotificationSource } from "../notifications";

export enum NotificationType {
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
  SUCCESS = "success",
}

export enum NotificationStatus {
  PENDING = "pending",
  DELIVERED = "delivered",
  READ = "read",
  SNOOZED = "snoozed",
  ARCHIVED = "archived",
}

export enum ActionType {
  REDIRECT = "redirect",
  API_CALL = "api_call",
  WORKFLOW = "workflow",
  MODAL = "modal",
}

export enum ActionStyle {
  PRIMARY = "primary",
  SECONDARY = "secondary",
  DANGER = "danger",
}

export interface RedirectConfig {
  url: string;
  open_in_new_tab?: boolean;
  close_notification?: boolean;
}

export interface ApiCallPayload {
  // Email operations
  message_ids?: string[];

  // Todo operations
  title?: string;
  description?: string;
  due_date?: string;
  priority?: "high" | "medium" | "low";
  project_id?: string;
  labels?: string[];
  completed?: boolean;

  // Calendar operations
  summary?: string;
  start?: { dateTime: string; timeZone?: string };
  end?: { dateTime: string; timeZone?: string };
  attendees?: Array<{ email: string; displayName?: string }>;
  location?: string;

  // Generic fields
  id?: string;
  ids?: string[];
  status?: string;
  filters?: Record<string, string | number | boolean>;
  page?: number;
  per_page?: number;

  // File operations
  filename?: string;
  content?: string;
  metadata?: Record<string, string | number | boolean>;
}

export interface ApiCallConfig {
  endpoint: string;
  method?: "GET" | "POST" | "PUT" | "DELETE";
  payload?: ApiCallPayload;
  headers?: Record<string, string>;
  success_message?: string;
  error_message?: string;
  is_internal?: boolean;
}

export interface WorkflowParameters {
  // Entity identifiers
  user_id?: string;
  notification_id?: string;
  entity_id?: string;
  entity_type?: "todo" | "calendar" | "email" | "goal" | "note";

  // Action parameters
  action?: string;
  delay_minutes?: number;
  conditions?: Array<{
    field: string;
    operator: "equals" | "contains" | "greater_than" | "less_than";
    value: string | number | boolean;
  }>;

  // Data context
  context?: {
    source?: string;
    trigger_event?: string;
    priority?: number;
    metadata?: Record<string, string | number | boolean>;
  };
}

export interface WorkflowConfig {
  workflow_id: string;
  parameters?: WorkflowParameters;
}

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
  goalId?: string;
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

export interface ModalConfig {
  component: string;
  props?: ModalProps;
}

export interface ActionConfig {
  redirect?: RedirectConfig;
  api_call?: ApiCallConfig;
  workflow?: WorkflowConfig;
  modal?: ModalConfig;
}

export interface NotificationAction {
  id: string;
  type: ActionType;
  label: string;
  style?: ActionStyle;
  config: ActionConfig;
  requires_confirmation?: boolean;
  confirmation_message?: string;
  icon?: string;
  disabled?: boolean;
  executed?: boolean;
  executed_at?: string; // ISO string
}

export interface RichContent {
  // Interactive elements
  buttons?: Array<{
    label: string;
    action: "redirect" | "api_call" | "modal";
    style?: "primary" | "secondary" | "danger";
    config?: ActionConfig;
  }>;

  // Media content
  images?: Array<{
    url: string;
    alt?: string;
    caption?: string;
  }>;

  // Structured data
  charts?: Array<{
    type: "bar" | "line" | "pie" | "scatter";
    title: string;
    data: Array<{
      label: string;
      value: number;
      group?: string;
    }>;
  }>;

  // Lists and tables
  lists?: Array<{
    title?: string;
    items: string[];
    ordered?: boolean;
  }>;

  tables?: Array<{
    headers: string[];
    rows: string[][];
  }>;

  // Embedded content
  embeds?: Array<{
    type: "calendar" | "todo" | "document";
    data: Record<string, string | number | boolean>;
  }>;
}

export interface NotificationContent {
  title: string;
  body: string;
  actions?: NotificationAction[];
  rich_content?: RichContent;
}

export interface ChannelConfiguration {
  // Email channel
  email?: {
    template?: string;
    from_address?: string;
    reply_to?: string;
    subject_prefix?: string;
    include_attachments?: boolean;
  };

  // Push notification channel
  push?: {
    title_template?: string;
    body_template?: string;
    icon?: string;
    badge?: number;
    sound?: string;
    click_action?: string;
  };

  // In-app notification channel
  in_app?: {
    position?: "top-right" | "top-left" | "bottom-right" | "bottom-left";
    duration_ms?: number;
    auto_dismiss?: boolean;
    show_actions?: boolean;
  };

  // SMS channel
  sms?: {
    template?: string;
    sender_id?: string;
    max_length?: number;
  };

  // Webhook channel
  webhook?: {
    url: string;
    method?: "POST" | "PUT";
    headers?: Record<string, string>;
    payload_template?: string;
    retry_count?: number;
  };
}

export interface ChannelConfig {
  channel_type: string;
  enabled?: boolean;
  priority?: number;
  template?: string;
  config?: ChannelConfiguration;
}

export interface NotificationMetadata {
  // Source tracking
  source?: "system" | "user" | "integration" | "workflow";
  source_id?: string;

  // Entity relationships
  reminder_id?: string;
  todo_id?: string;
  calendar_event_id?: string;
  email_id?: string;
  goal_id?: string;
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

export interface NotificationRequest {
  id: string;
  user_id: string;
  source: string;
  type: NotificationType;
  priority?: number;
  channels: ChannelConfig[];
  content: NotificationContent;
  metadata?: NotificationMetadata;
  scheduled_for?: string;
  created_at: string;
}

export interface ChannelDeliveryStatus {
  channel_type: string;
  status: NotificationStatus;
  delivered_at?: string;
  error_message?: string;
  retry_count?: number;
}

export interface NotificationRecord {
  id: string;
  user_id: string;
  status: NotificationStatus;
  created_at: string;
  delivered_at?: string;
  read_at?: string;
  source: NotificationSource;
  content: NotificationContent;
  metadata?: NotificationMetadata;
  channels: ChannelDeliveryStatus[];
}

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
  status?: NotificationStatus;
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
  DELETE = "delete",
}

export interface SnoozeSettings {
  // Default snooze durations (in minutes)
  default_duration?: number;
  quick_options?: number[]; // e.g., [15, 30, 60, 120, 480] for 15min, 30min, 1hr, 2hr, 8hr

  // Maximum snooze limits
  max_duration?: number;
  max_snoozes_per_notification?: number;

  // Smart snooze features
  smart_snooze?: {
    enabled: boolean;
    work_hours_only?: boolean;
    avoid_weekends?: boolean;
    time_zone?: string;
  };

  // Recurring snooze patterns
  recurring_patterns?: Array<{
    name: string;
    duration: number;
    repeat_count?: number;
    conditions?: Array<{
      field: string;
      operator: string;
      value: string | number | boolean;
    }>;
  }>;

  // Per-category settings
  category_overrides?: Record<
    string,
    {
      default_duration: number;
      max_duration: number;
      quick_options: number[];
    }
  >;
}

export interface NotificationPreferences {
  user_id: string;
  channel_preferences?: Record<string, Record<string, boolean | number>>;
  snooze_settings?: SnoozeSettings;
  quiet_hours?: Record<string, string>;
  max_notifications_per_hour?: number;
  updated_at: string;
}

// API Request/Response types
export interface CreateNotificationRequest {
  notification_request: NotificationRequest;
}

export interface BulkActionRequest {
  notification_ids: string[];
  action: BulkActions;
}

export interface SnoozeRequest {
  snooze_until: string;
}

export interface NotificationResponse {
  success: boolean;
  message: string;
  data?: ActionResultData | NotificationRecord; // Allow both types
}

export interface PaginatedNotificationsResponse {
  notifications: NotificationRecord[];
  total: number;
  limit: number;
  offset: number;
}

// Hook options
export interface UseNotificationsOptions {
  status?: NotificationStatus;
  limit?: number;
  offset?: number;
  channel_type?: string;
}
