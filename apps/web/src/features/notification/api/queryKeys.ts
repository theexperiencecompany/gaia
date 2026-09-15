import type { UseNotificationsOptions } from "@/types/features/notificationTypes";

/**
 * Canonical React Query keys for notifications.
 *
 * The list key carries every filter the fetch depends on (status, channel_type,
 * limit, offset) so two different views can never collide on one cache entry —
 * the exact failure mode of the hand-rolled store this replaces, which held a
 * single unkeyed page for the whole app.
 *
 * There is no server-side count endpoint (`/notifications` returns the page and
 * a `total`), so the unread badge is derived from the list query rather than
 * being its own key. If a `/notifications/count` endpoint is ever added, give it
 * a `count(filters)` member here rather than reintroducing a store.
 */
export const notificationKeys = {
  /** Prefix — invalidating this busts every notification list. */
  all: ["notifications"] as const,
  /** One page of notifications for a specific filter set. */
  list: (filters: UseNotificationsOptions = {}) =>
    [
      "notifications",
      "list",
      {
        status: filters.status ?? null,
        channel_type: filters.channel_type ?? null,
        limit: filters.limit ?? null,
        offset: filters.offset ?? null,
      },
    ] as const,
};
