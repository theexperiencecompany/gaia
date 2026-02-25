import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/toast";

import { NotificationsAPI } from "@/services/api/notifications";
import { useNotificationStore } from "@/stores/notificationStore";
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
  const {
    notifications: allNotifications,
    isLoaded,
    setNotifications,
    addNotification,
    updateNotification,
  } = useNotificationStore();

  const [loading, setLoading] = useState(!isLoaded);
  const [error, setError] = useState<string | null>(null);

  const { limit, offset, channel_type } = options;
  // setFetching accessed via store.getState() inside fetchNotifications

  // Always fetch without status filter so the store has the full dataset.
  // Status filtering is applied client-side via the memoized `notifications` below.
  const fetchNotifications = useCallback(
    async (force = false) => {
      const state = useNotificationStore.getState();
      if (!force && (state.isLoaded || state.isFetching)) {
        setLoading(false);
        return;
      }
      state.setFetching(true);
      try {
        setLoading(true);
        setError(null);
        const response = await NotificationsAPI.getNotifications({
          limit: Math.max(limit ?? 0, 100),
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
        useNotificationStore.getState().setFetching(false);
        setLoading(false);
      }
    },
    [limit, offset, channel_type, setNotifications],
  );

  const markAsRead = useCallback(
    async (id: string) => {
      try {
        updateNotification({
          ...allNotifications.find((n) => n.id === id)!,
          status: NotificationStatus.READ,
          read_at: new Date().toISOString(),
        });

        await NotificationsAPI.markAsRead(id);
        await fetchNotifications(true);
        toast.success("Notification marked as read");
      } catch (error) {
        await fetchNotifications(true);
        toast.error("Failed to mark notification as read");
        console.error("Error marking notification as read:", error);
      }
    },
    [allNotifications, updateNotification, fetchNotifications],
  );

  const archiveNotification = useCallback(
    async (id: string) => {
      try {
        await NotificationsAPI.archiveNotification(id);
        await fetchNotifications(true);
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
        await fetchNotifications(true);
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
        await fetchNotifications(true);
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
        await fetchNotifications(true);
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
        await fetchNotifications(true);
        toast.success(`${ids.length} notifications deleted`);
      } catch (error) {
        toast.error("Failed to delete notifications");
        console.error("Error bulk deleting notifications:", error);
      }
    },
    [fetchNotifications],
  );

  // Apply client-side status filtering; the store holds all statuses
  const notifications = useMemo(() => {
    let result = allNotifications;
    if (options.status) {
      result = result.filter((n) => n.status === options.status);
    }
    if (limit) {
      result = result.slice(0, limit);
    }
    return result;
  }, [allNotifications, options.status, limit]);

  const unreadCount = useMemo(
    () =>
      notifications.filter(
        (notification) => notification.status === NotificationStatus.DELIVERED,
      ).length,
    [notifications],
  );

  // Initial fetch — skipped if store is already populated
  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  return {
    notifications,
    loading,
    error,
    refetch: () => fetchNotifications(true),
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
