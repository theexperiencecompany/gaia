import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { NotificationsAPI } from "@/services/api/notifications";
import {
  type NotificationRecord,
  NotificationStatus,
  type UseNotificationsOptions,
} from "@/types/features/notificationTypes";

interface UseNotificationsReturn {
  notifications: NotificationRecord[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  markAsRead: (id: string) => Promise<void>;
  archiveNotification: (id: string) => Promise<void>;
  snoozeNotification: (id: string, until: Date) => Promise<void>;
  bulkMarkAsRead: (ids: string[]) => Promise<void>;
  bulkArchive: (ids: string[]) => Promise<void>;
  bulkDelete: (ids: string[]) => Promise<void>;
  unreadCount: number;
  addNotification: (notification: NotificationRecord) => void;
  updateNotification: (notification: NotificationRecord) => void;
}

export function useNotifications(
  options: UseNotificationsOptions = {},
): UseNotificationsReturn {
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { status, limit, offset, channel_type } = options;

  const fetchNotifications = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await NotificationsAPI.getNotifications({
        status,
        limit,
        offset,
        channel_type,
      });
      setNotifications(response.notifications);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to fetch notifications";
      setError(errorMessage);
      console.error("Error fetching notifications:", err);
    } finally {
      setLoading(false);
    }
  }, [status, limit, offset, channel_type]);

  const markAsRead = useCallback(
    async (id: string) => {
      try {
        // Optimistically update local state first for immediate UI feedback
        setNotifications((prev) =>
          prev.map((notification) =>
            notification.id === id
              ? {
                  ...notification,
                  status: NotificationStatus.READ,
                  read_at: new Date().toISOString(),
                }
              : notification,
          ),
        );

        // Make API call
        await NotificationsAPI.markAsRead(id);

        // Refetch to ensure consistency with backend
        await fetchNotifications();
        toast.success("Notification marked as read");
      } catch (error) {
        // Revert optimistic update on error
        await fetchNotifications();
        toast.error("Failed to mark notification as read");
        console.error("Error marking notification as read:", error);
      }
    },
    [fetchNotifications],
  );

  const archiveNotification = useCallback(
    async (id: string) => {
      try {
        await NotificationsAPI.archiveNotification(id);
        await fetchNotifications();
        toast.success("Notification archived");
      } catch (error) {
        toast.error("Failed to archive notification");
        console.error("Error archiving notification:", error);
      }
    },
    [fetchNotifications],
  );

  const snoozeNotification = useCallback(
    async (id: string, until: Date) => {
      try {
        await NotificationsAPI.snoozeNotification(id, until);
        await fetchNotifications();
        toast.success("Notification snoozed");
      } catch (error) {
        toast.error("Failed to snooze notification");
        console.error("Error snoozing notification:", error);
      }
    },
    [fetchNotifications],
  );

  const bulkMarkAsRead = useCallback(
    async (ids: string[]) => {
      try {
        await NotificationsAPI.bulkMarkAsRead(ids);
        await fetchNotifications();
        toast.success(`Marked ${ids.length} notifications as read`);
      } catch (error) {
        toast.error("Failed to mark notifications as read");
        console.error("Error bulk marking notifications as read:", error);
      }
    },
    [fetchNotifications],
  );

  const bulkArchive = useCallback(
    async (ids: string[]) => {
      try {
        await NotificationsAPI.bulkArchive(ids);
        await fetchNotifications();
        toast.success(`${ids.length} notifications archived`);
      } catch (error) {
        toast.error("Failed to archive notifications");
        console.error("Error bulk archiving notifications:", error);
      }
    },
    [fetchNotifications],
  );

  const bulkDelete = useCallback(
    async (ids: string[]) => {
      try {
        await NotificationsAPI.bulkDelete(ids);
        await fetchNotifications();
        toast.success(`${ids.length} notifications deleted`);
      } catch (error) {
        toast.error("Failed to delete notifications");
        console.error("Error bulk deleting notifications:", error);
      }
    },
    [fetchNotifications],
  );

  const addNotification = useCallback((notification: NotificationRecord) => {
    setNotifications((prev) => [notification, ...prev]);
  }, []);

  const updateNotification = useCallback(
    (updatedNotification: NotificationRecord) => {
      setNotifications((prev) =>
        prev.map((notification) =>
          notification.id === updatedNotification.id
            ? updatedNotification
            : notification,
        ),
      );
    },
    [],
  );

  // Calculate unread count
  const unreadCount = notifications.filter(
    (notification) => notification.status === NotificationStatus.DELIVERED,
  ).length;

  // Initial fetch
  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  return {
    notifications,
    loading,
    error,
    refetch: fetchNotifications,
    markAsRead,
    archiveNotification,
    snoozeNotification,
    bulkMarkAsRead,
    bulkArchive,
    bulkDelete,
    unreadCount,
    addNotification,
    updateNotification,
  };
}
