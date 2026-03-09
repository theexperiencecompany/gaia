export enum InAppNotificationStatus {
  PENDING = "pending",
  DELIVERED = "delivered",
  READ = "read",
  ARCHIVED = "archived",
}

export enum InAppNotificationActionType {
  REDIRECT = "redirect",
  API_CALL = "api_call",
  WORKFLOW = "workflow",
  MODAL = "modal",
}

export enum InAppNotificationActionStyle {
  PRIMARY = "primary",
  SECONDARY = "secondary",
  DANGER = "danger",
}

export interface InAppNotificationActionConfig {
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

export interface InAppNotificationAction {
  id: string;
  type: InAppNotificationActionType;
  label: string;
  style?: InAppNotificationActionStyle;
  config: InAppNotificationActionConfig;
  executed?: boolean;
  disabled?: boolean;
}

export interface InAppNotificationContent {
  title: string;
  body: string;
  actions?: InAppNotificationAction[];
}

export interface InAppNotification {
  id: string;
  status: InAppNotificationStatus;
  source?: string;
  type?: string;
  created_at: string;
  read_at?: string | null;
  content: InAppNotificationContent;
}

export interface InAppNotificationsListResponse {
  notifications: InAppNotification[];
  total: number;
  limit: number;
  offset: number;
}

export interface NotificationActionResponse {
  success: boolean;
  message: string;
  data?: {
    redirect_url?: string;
    [key: string]: unknown;
  };
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
