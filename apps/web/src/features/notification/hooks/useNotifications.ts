import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import {
  patchNotifications,
  prependNotification,
  removeNotifications,
  restoreNotificationPages,
  snapshotNotificationPages,
  upsertNotification,
} from "@/features/notification/api/notificationCache";
import { notificationKeys } from "@/features/notification/api/queryKeys";
import { NOTIFICATION_PAGE_SIZE } from "@/features/notification/constants";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  NotificationStatus,
  type NotificationView,
  type UseNotificationsOptions,
} from "@/types/features/notificationTypes";

interface UseNotificationsReturn {
  notifications: NotificationView[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  markAsRead: (id: string) => Promise<void>;
  archiveNotification: (id: string) => Promise<void>;
  bulkMarkAsRead: (ids: string[]) => Promise<void>;
  bulkArchive: (ids: string[]) => Promise<void>;
  markAllAsRead: (channelType?: string) => Promise<void>;
  unreadCount: number;
  /** True when the shared store hit its fetch cap, so `unreadCount` may
   * undercount — an older delivered notification could exist past the loaded
   * page. Callers gating "is there anything to mark read" must OR this in
   * rather than trust `unreadCount === 0` alone. */
  hasMoreUnseen: boolean;
  addNotification: (notification: NotificationView) => void;
  updateNotification: (notification: NotificationView) => void;
}

// `offset` is deliberately not accepted: the UI does not page. The query key
// still carries offset (notificationKeys.list), so a future paged caller gets
// a new key, not the cache collision the old single-entry store couldn't avoid.
type UseNotificationsHookOptions = Omit<UseNotificationsOptions, "offset">;

// One canonical request for the whole app: the first unfiltered page at the
// API's max size. Caller status/channel/limit are view-level, applied
// client-side below — a caller's `limit` here would mismatch other mounts and could 422 above the API's ceiling.
const CANONICAL_FILTERS: UseNotificationsOptions = {
  limit: NOTIFICATION_PAGE_SIZE,
};

const EMPTY: NotificationView[] = [];

/**
 * Mark every cached DELIVERED notification read, optionally only those sent on
 * `channelType`. Shared by the mark-all mutation and the `notification.all_read`
 * websocket push so both views of "all read" patch the cache identically.
 */
export function markDeliveredAsReadInCache(
  queryClient: QueryClient,
  channelType?: string | null,
): void {
  const ids = new Set<string>();
  for (const [, page] of snapshotNotificationPages(queryClient)) {
    for (const n of page?.notifications ?? []) {
      if (n.status !== NotificationStatus.DELIVERED) continue;
      if (
        channelType &&
        !n.channels?.some((c) => c.channel_type === channelType)
      ) {
        continue;
      }
      ids.add(n.id);
    }
  }
  if (ids.size === 0) return;
  patchNotifications(queryClient, [...ids], {
    status: NotificationStatus.READ,
    read_at: new Date().toISOString(),
  });
}

export function useNotifications(
  options: UseNotificationsHookOptions = {},
): UseNotificationsReturn {
  const queryClient = useQueryClient();
  const listKey = notificationKeys.list(CANONICAL_FILTERS);

  const query = useQuery({
    queryKey: listKey,
    queryFn: () => NotificationsAPI.getNotifications(CANONICAL_FILTERS),
    staleTime: 30_000,
  });

  const allNotifications = query.data?.notifications ?? EMPTY;

  const refetch = useCallback(async () => {
    await query.refetch();
  }, [query]);

  const markAsReadMutation = useMutation({
    mutationFn: (id: string) => NotificationsAPI.markAsRead(id),
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });
      const snapshot = snapshotNotificationPages(queryClient);
      patchNotifications(queryClient, [id], {
        status: NotificationStatus.READ,
        read_at: new Date().toISOString(),
      });
      return { snapshot };
    },
    // No success toast: the optimistic cache write already shows it read.
    onError: (error, _id, context) => {
      if (context?.snapshot) {
        restoreNotificationPages(queryClient, context.snapshot);
      }
      toast.error("Failed to mark notification as read");
      console.error("Error marking notification as read:", error);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });

  const bulkMarkAsReadMutation = useMutation({
    mutationFn: (ids: string[]) => NotificationsAPI.bulkMarkAsRead(ids),
    onMutate: async (ids: string[]) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });
      const snapshot = snapshotNotificationPages(queryClient);
      patchNotifications(queryClient, ids, {
        status: NotificationStatus.READ,
        read_at: new Date().toISOString(),
      });
      return { snapshot };
    },
    onSuccess: (_data, ids) =>
      toast.success(`Marked ${ids.length} notifications as read`),
    onError: (error, _ids, context) => {
      if (context?.snapshot) {
        restoreNotificationPages(queryClient, context.snapshot);
      }
      toast.error("Failed to mark notifications as read");
      console.error("Error bulk marking notifications as read:", error);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });

  // Server-side mark-all (every delivered notification, not just the loaded
  // page); the cache is patched optimistically for what is loaded.
  const markAllAsReadMutation = useMutation({
    mutationFn: (channelType?: string) =>
      NotificationsAPI.markAllAsRead(channelType),
    onMutate: async (channelType?: string) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });
      const snapshot = snapshotNotificationPages(queryClient);
      markDeliveredAsReadInCache(queryClient, channelType);
      return { snapshot };
    },
    onSuccess: (response) => {
      toast.success(
        `Marked ${response.data?.updated_count ?? 0} notifications as read`,
      );
    },
    onError: (error, _channelType, context) => {
      if (context?.snapshot) {
        restoreNotificationPages(queryClient, context.snapshot);
      }
      toast.error("Failed to mark all notifications as read");
      console.error("Error marking all notifications as read:", error);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (ids: string[]) =>
      ids.length === 1
        ? NotificationsAPI.archiveNotification(ids[0])
        : NotificationsAPI.bulkArchive(ids),
    onMutate: async (ids: string[]) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.all });
      const snapshot = snapshotNotificationPages(queryClient);
      removeNotifications(queryClient, ids);
      return { snapshot };
    },
    onError: (error, ids, context) => {
      if (context?.snapshot) {
        restoreNotificationPages(queryClient, context.snapshot);
      }
      toast.error(
        ids.length === 1
          ? "Failed to archive notification"
          : "Failed to archive notifications",
      );
      console.error("Error archiving notifications:", error);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });

  const markAsRead = useCallback(
    async (id: string) => {
      // The mutation reports failure through its own onError/toast; swallowing
      // the rejection here keeps the caller's `await` from throwing, matching
      // the previous hook's contract.
      await markAsReadMutation.mutateAsync(id).catch(() => undefined);
    },
    [markAsReadMutation],
  );

  const bulkMarkAsRead = useCallback(
    async (ids: string[]) => {
      await bulkMarkAsReadMutation.mutateAsync(ids).catch(() => undefined);
    },
    [bulkMarkAsReadMutation],
  );

  const archiveNotification = useCallback(
    async (id: string) => {
      const ok = await archiveMutation
        .mutateAsync([id])
        .then(() => true)
        .catch(() => false);
      if (ok) toast.success("Notification archived");
    },
    [archiveMutation],
  );

  const markAllAsRead = useCallback(
    async (channelTypeFilter?: string) => {
      await markAllAsReadMutation
        .mutateAsync(channelTypeFilter)
        .catch(() => undefined);
    },
    [markAllAsReadMutation],
  );

  const bulkArchive = useCallback(
    async (ids: string[]) => {
      const ok = await archiveMutation
        .mutateAsync(ids)
        .then(() => true)
        .catch(() => false);
      if (ok) toast.success(`${ids.length} notifications archived`);
    },
    [archiveMutation],
  );

  const addNotification = useCallback(
    (notification: NotificationView) =>
      prependNotification(queryClient, notification),
    [queryClient],
  );

  const updateNotification = useCallback(
    (notification: NotificationView) =>
      upsertNotification(queryClient, notification),
    [queryClient],
  );

  // Narrow the shared page down to this caller's view.
  const notifications = useMemo(() => {
    let result = allNotifications;
    if (options.status) {
      result = result.filter((n) => n.status === options.status);
    }
    if (options.channel_type) {
      result = result.filter((n) =>
        n.channels?.some((c) => c.channel_type === options.channel_type),
      );
    }
    if (options.limit) {
      result = result.slice(0, options.limit);
    }
    return result;
  }, [allNotifications, options.status, options.channel_type, options.limit]);

  // Counted from the full fetched page, not the status/limit-sliced view, so the
  // badge reflects every loaded unread notification.
  const unreadCount = useMemo(
    () =>
      allNotifications.filter(
        (notification) => notification.status === NotificationStatus.DELIVERED,
      ).length,
    [allNotifications],
  );

  // The shared fetch is capped at NOTIFICATION_PAGE_SIZE — if it came back
  // full, an older, still-unread notification may exist beyond what's loaded.
  const hasMoreUnseen = allNotifications.length >= NOTIFICATION_PAGE_SIZE;

  return {
    notifications,
    loading: query.isPending,
    error: query.error
      ? query.error instanceof Error
        ? query.error.message
        : "Failed to fetch notifications"
      : null,
    refetch,
    markAsRead,
    archiveNotification,
    bulkMarkAsRead,
    bulkArchive,
    markAllAsRead,
    unreadCount,
    hasMoreUnseen,
    addNotification,
    updateNotification,
  };
}
