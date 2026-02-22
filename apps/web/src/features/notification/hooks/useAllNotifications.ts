import { useCallback, useEffect, useState } from "react";
import { toast } from "@/lib/toast";

import { NotificationsAPI } from "@/services/api/notifications";
import {
  type NotificationRecord,
  NotificationStatus,
  type UseNotificationsOptions,
} from "@/types/features/notificationTypes";

interface UseAllNotificationsReturn {
  allNotifications: NotificationRecord[];
  readNotifications: NotificationRecord[];
  unreadNotifications: NotificationRecord[];
  loading: boolean;
  error: string | null;
  refetchAll: () => Promise<void>;
  refetchRead: () => Promise<void>;
  refetchUnread: () => Promise<void>;
  markAsRead: (id: string) => Promise<void>;
  addNotification: (notification: NotificationRecord) => void;
  updateNotification: (notification: NotificationRecord) => void;
}

export function useAllNotifications(
  options: Omit<UseNotificationsOptions, "status"> = {},
): UseAllNotificationsReturn {
  const [allNotifications, setAllNotifications] = useState<
    NotificationRecord[]
  >([]);
  const [readNotifications, setReadNotifications] = useState<
    NotificationRecord[]
  >([]);
  const [unreadNotifications, setUnreadNotifications] = useState<
    NotificationRecord[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { limit, offset, channel_type } = options;

  const fetchAllNotifications = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await NotificationsAPI.getNotifications({
        limit,
        offset,
        channel_type,
      });
      setAllNotifications(response.notifications);
    } catch (err) {
      const errorMessage =
        err instanceof Error
          ? err.message
          : "Failed to fetch all notifications";
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [limit, offset, channel_type]);

  const fetchReadNotifications = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await NotificationsAPI.getReadNotifications({
        limit,
        offset,
        channel_type,
      });
      setReadNotifications(response.notifications);
    } catch (err) {
      const errorMessage =
        err instanceof Error
          ? err.message
          : "Failed to fetch read notifications";
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [limit, offset, channel_type]);

  const fetchUnreadNotifications = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await NotificationsAPI.getNotifications({
        status: NotificationStatus.DELIVERED,
        limit,
        offset,
        channel_type,
      });
      setUnreadNotifications(response.notifications);
    } catch (err) {
      const errorMessage =
        err instanceof Error
          ? err.message
          : "Failed to fetch unread notifications";
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [limit, offset, channel_type]);

  const markAsRead = useCallback(
    async (id: string) => {
      try {
        // Optimistically update local state first for immediate UI feedback
        const updateNotificationState = (prev: NotificationRecord[]) =>
          prev.map((n) =>
            n.id === id
              ? {
                  ...n,
                  status: NotificationStatus.READ,
                  read_at: new Date().toISOString(),
                }
              : n,
          );

        // Find the notification before updating
        const notificationToMove = allNotifications.find((n) => n.id === id);

        // Update all local states optimistically
        setAllNotifications(updateNotificationState);
        setUnreadNotifications((prev) => prev.filter((n) => n.id !== id));

        // Add to read notifications if not already there
        if (notificationToMove) {
          const updatedNotification = {
            ...notificationToMove,
            status: NotificationStatus.READ,
            read_at: new Date().toISOString(),
          };
          setReadNotifications((prev) => {
            // Check if already exists to avoid duplicates
            const exists = prev.some((n) => n.id === id);
            return exists
              ? updateNotificationState(prev)
              : [updatedNotification, ...prev];
          });
        }

        // Make API call
        await NotificationsAPI.markAsRead(id);

        toast.success("Notification marked as read");
      } catch (err) {
        // Revert optimistic updates on error by refetching
        await Promise.all([
          fetchAllNotifications(),
          fetchReadNotifications(),
          fetchUnreadNotifications(),
        ]);

        const errorMessage =
          err instanceof Error
            ? err.message
            : "Failed to mark notification as read";
        toast.error(errorMessage);
      }
    },
    [
      allNotifications,
      fetchAllNotifications,
      fetchReadNotifications,
      fetchUnreadNotifications,
    ],
  );

  const addNotification = useCallback((notification: NotificationRecord) => {
    setAllNotifications((prev) => [notification, ...prev]);
    if (notification.status === NotificationStatus.DELIVERED) {
      setUnreadNotifications((prev) => [notification, ...prev]);
    } else if (notification.status === NotificationStatus.READ) {
      setReadNotifications((prev) => [notification, ...prev]);
    }
  }, []);

  const updateNotification = useCallback(
    (updatedNotification: NotificationRecord) => {
      const updateList = (prev: NotificationRecord[]) =>
        prev.map((n) =>
          n.id === updatedNotification.id ? updatedNotification : n,
        );

      setAllNotifications(updateList);
      setReadNotifications(updateList);
      setUnreadNotifications(updateList);
    },
    [],
  );

  useEffect(() => {
    fetchAllNotifications();
  }, [fetchAllNotifications]);

  return {
    allNotifications,
    readNotifications,
    unreadNotifications,
    loading,
    error,
    refetchAll: fetchAllNotifications,
    refetchRead: fetchReadNotifications,
    refetchUnread: fetchUnreadNotifications,
    markAsRead,
    addNotification,
    updateNotification,
  };
}
