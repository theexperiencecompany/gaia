export enum NotificationStatus {
  PENDING = "pending",
  DELIVERED = "delivered",
  READ = "read",
  SNOOZED = "snoozed",
  ARCHIVED = "archived",
}

export enum NotificationActionType {
  REDIRECT = "redirect",
  API_CALL = "api_call",
  WORKFLOW = "workflow",
  MODAL = "modal",
}

export enum NotificationActionStyle {
  PRIMARY = "primary",
  SECONDARY = "secondary",
  DANGER = "danger",
}

export interface NotificationActionConfig {
  redirect?: {
    url: string;
    open_in_new_tab?: boolean;
    close_notification?: boolean;
  };
  api_call?: {
    endpoint: string;
    method?: "GET" | "POST" | "PUT" | "DELETE";
    payload?: Record<string, unknown>;
  };
  workflow?: {
    workflow_id: string;
    parameters?: Record<string, unknown>;
  };
  modal?: {
    component: string;
    props?: Record<string, unknown>;
  };
}

export interface NotificationAction {
  id: string;
  type: NotificationActionType;
  label: string;
  style?: NotificationActionStyle;
  config: NotificationActionConfig;
  executed?: boolean;
  disabled?: boolean;
}

export interface InAppNotificationContent {
  title: string;
  body: string;
  actions?: NotificationAction[];
}

export interface InAppNotification {
  id: string;
  status: NotificationStatus;
  source?: string;
  type?: string;
  created_at: string;
  read_at?: string | null;
  content: InAppNotificationContent;
}

export interface PlatformLink {
  platform: string;
  platformUserId: string;
  username?: string;
  displayName?: string;
  connectedAt?: string;
}

export interface PlatformLinksResponse {
  platform_links: Record<string, PlatformLink>;
}
