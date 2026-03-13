import { NotificationStatus } from "../types/notification";
import type { InAppNotification } from "../types/notification";

export const NotificationQueryKeys = {
  all: ["notifications"] as const,
  list: (params?: Record<string, unknown>) =>
    params
      ? ([...NotificationQueryKeys.all, "list", params] as const)
      : ([...NotificationQueryKeys.all, "list"] as const),
  unread: () => [...NotificationQueryKeys.all, "unread"] as const,
  archived: () => [...NotificationQueryKeys.all, "archived"] as const,
  detail: (id: string) =>
    [...NotificationQueryKeys.all, "detail", id] as const,
};

export interface NotificationFilter {
  unreadOnly?: boolean;
  type?: string;
  source?: string;
}

export function filterNotifications(
  notifications: InAppNotification[],
  filter: NotificationFilter,
): InAppNotification[] {
  return notifications.filter((notification) => {
    if (filter.unreadOnly) {
      const isUnread =
        notification.status === NotificationStatus.DELIVERED ||
        notification.status === NotificationStatus.PENDING;
      if (!isUnread) return false;
    }

    if (filter.type && notification.type !== filter.type) {
      return false;
    }

    if (filter.source && notification.source !== filter.source) {
      return false;
    }

    return true;
  });
}

export function groupNotificationsByDate(
  notifications: InAppNotification[],
): Record<string, InAppNotification[]> {
  const groups: Record<string, InAppNotification[]> = {};

  for (const notification of notifications) {
    const date = new Date(notification.created_at);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    let key: string;

    if (
      date.getFullYear() === today.getFullYear() &&
      date.getMonth() === today.getMonth() &&
      date.getDate() === today.getDate()
    ) {
      key = "Today";
    } else if (
      date.getFullYear() === yesterday.getFullYear() &&
      date.getMonth() === yesterday.getMonth() &&
      date.getDate() === yesterday.getDate()
    ) {
      key = "Yesterday";
    } else {
      key = date.toISOString().split("T")[0];
    }

    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(notification);
  }

  return groups;
}

export function getNotificationIcon(type: string): string {
  const iconMap: Record<string, string> = {
    task: "CheckCircle",
    todo: "CheckCircle",
    workflow: "Zap",
    calendar: "Calendar",
    reminder: "Bell",
    message: "MessageSquare",
    chat: "MessageSquare",
    alert: "AlertTriangle",
    warning: "AlertTriangle",
    error: "XCircle",
    success: "CheckCircle2",
    info: "Info",
    system: "Settings",
    integration: "Plug",
    email: "Mail",
    update: "RefreshCw",
  };

  const normalizedType = type.toLowerCase();
  return iconMap[normalizedType] ?? "Bell";
}

