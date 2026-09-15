import type { QueryClient } from "@tanstack/react-query";

import { notificationKeys } from "@/features/notification/api/queryKeys";
import type {
  NotificationRecord,
  PaginatedNotificationsResponse,
} from "@/types/features/notificationTypes";

type Page = PaginatedNotificationsResponse | undefined;

/**
 * Apply `update` to every cached notification page.
 *
 * Writes go to all keys under `notificationKeys.all` rather than one list key:
 * a websocket push or a mutation is true for every view that is currently
 * showing the affected notification, whatever filters that view used.
 */
function updateAllPages(
  queryClient: QueryClient,
  update: (
    page: PaginatedNotificationsResponse,
  ) => PaginatedNotificationsResponse,
): void {
  queryClient.setQueriesData<Page>(
    { queryKey: notificationKeys.all },
    (page) => {
      if (!page || !Array.isArray(page.notifications)) return page;
      return update(page);
    },
  );
}

/** Prepend a newly delivered notification; a duplicate id is a no-op. */
export function prependNotification(
  queryClient: QueryClient,
  notification: NotificationRecord,
): void {
  updateAllPages(queryClient, (page) => {
    if (page.notifications.some((n) => n.id === notification.id)) return page;
    return {
      ...page,
      notifications: [notification, ...page.notifications],
      // `total` is the server's count for the filter; keep it consistent with
      // the row we just added so a badge reading it does not lag by one.
      total: (page.total ?? page.notifications.length) + 1,
    };
  });
}

/** Replace a notification in place; unknown ids are ignored. */
export function upsertNotification(
  queryClient: QueryClient,
  notification: NotificationRecord,
): void {
  updateAllPages(queryClient, (page) => ({
    ...page,
    notifications: page.notifications.map((n) =>
      n.id === notification.id ? notification : n,
    ),
  }));
}

/** Patch a set of notifications by id (optimistic mutations). */
export function patchNotifications(
  queryClient: QueryClient,
  ids: string[],
  patch: Partial<NotificationRecord>,
): void {
  const idSet = new Set(ids);
  updateAllPages(queryClient, (page) => ({
    ...page,
    notifications: page.notifications.map((n) =>
      idSet.has(n.id) ? { ...n, ...patch } : n,
    ),
  }));
}

/** Remove notifications by id (optimistic archive). */
export function removeNotifications(
  queryClient: QueryClient,
  ids: string[],
): void {
  const idSet = new Set(ids);
  updateAllPages(queryClient, (page) => {
    const notifications = page.notifications.filter((n) => !idSet.has(n.id));
    if (notifications.length === page.notifications.length) return page;
    return {
      ...page,
      notifications,
      total: Math.max(
        0,
        (page.total ?? page.notifications.length) -
          (page.notifications.length - notifications.length),
      ),
    };
  });
}

/**
 * Snapshot every notification page so `onError` can restore them verbatim.
 * Returned as key/value pairs because the set of cached keys is not known here.
 */
export function snapshotNotificationPages(
  queryClient: QueryClient,
): [readonly unknown[], Page][] {
  return queryClient.getQueriesData<Page>({ queryKey: notificationKeys.all });
}

/** Restore a snapshot taken by `snapshotNotificationPages`. */
export function restoreNotificationPages(
  queryClient: QueryClient,
  snapshot: [readonly unknown[], Page][],
): void {
  for (const [key, page] of snapshot) {
    queryClient.setQueryData(key, page);
  }
}
