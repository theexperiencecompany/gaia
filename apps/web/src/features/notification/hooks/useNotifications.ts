import { useCallback, useEffect, useMemo, useState } from "react";
import { NOTIFICATION_PAGE_SIZE } from "@/features/notification/constants";
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
  bulkMarkAsRead: (ids: string[]) => Promise<void>;
  bulkArchive: (ids: string[]) => Promise<void>;
  unreadCount: number;
  addNotification: (notification: NotificationRecord) => void;
  updateNotification: (notification: NotificationRecord) => void;
}

// `offset` is deliberately not accepted: the store is a single unkeyed entry
// shared by every mount, so it cannot represent a page other than the first.
// Excluding it makes that a compile error instead of a silent wrong page.
type UseNotificationsHookOptions = Omit<UseNotificationsOptions, "offset">;

export function useNotifications(
  options: UseNotificationsHookOptions = {},
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

  const { limit, channel_type } = options;
  // setFetching accessed via store.getState() inside fetchNotifications

  // One canonical request for the whole app: the first unfiltered page, at the
  // API's maximum size. Caller options never reach the wire — status, channel
  // and limit are view-level and applied client-side in the memo below. Sending
  // a caller's `limit` here would both fetch a page that doesn't match what the
  // other mounts expect and 422 for any value above the API's ceiling.
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
          limit: NOTIFICATION_PAGE_SIZE,
        });
        setNotifications(response.notifications ?? []);
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
    [setNotifications],
  );

  const refetch = useCallback(
    () => fetchNotifications(true),
    [fetchNotifications],
  );

  const markAsRead = useCallback(
    async (id: string) => {
      const existing = (allNotifications ?? []).find((n) => n.id === id);
      try {
        if (existing) {
          updateNotification({
            ...existing,
            status: NotificationStatus.READ,
            read_at: new Date().toISOString(),
          });
        }

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

  const bulkMarkAsRead = useCallback(
    async (ids: string[]) => {
      const idSet = new Set(ids);
      const prev = useNotificationStore.getState().notifications;
      setNotifications(
        prev.map((n) =>
          idSet.has(n.id) ? { ...n, status: NotificationStatus.READ } : n,
        ),
      );
      try {
        await NotificationsAPI.bulkMarkAsRead(ids);
        toast.success(`Marked ${ids.length} notifications as read`);
      } catch (error) {
        await fetchNotifications(true);
        toast.error("Failed to mark notifications as read");
        console.error("Error bulk marking notifications as read:", error);
      }
    },
    [fetchNotifications, setNotifications],
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

  // Narrow the shared store down to this caller's view. `?? []` is the last
  // line of defence — the API layer already rejects a malformed payload.
  const notifications = useMemo(() => {
    let result = allNotifications ?? [];
    if (options.status) {
      result = result.filter((n) => n.status === options.status);
    }
    if (channel_type) {
      result = result.filter((n) =>
        n.channels?.some((c) => c.channel_type === channel_type),
      );
    }
    if (limit) {
      result = result.slice(0, limit);
    }
    return result;
  }, [allNotifications, options.status, channel_type, limit]);

  // Count unread from the full fetched set, not the status/limit-sliced view, so
  // the badge reflects every loaded unread notification (not just the first page).
  const unreadCount = useMemo(
    () =>
      (allNotifications ?? []).filter(
        (notification) => notification.status === NotificationStatus.DELIVERED,
      ).length,
    [allNotifications],
  );

  // Initial fetch — skipped if store is already populated
  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  return {
    notifications,
    loading,
    error,
    refetch,
    markAsRead,
    archiveNotification,
    bulkMarkAsRead,
    bulkArchive,
    unreadCount,
    addNotification,
    updateNotification,
  };
}
