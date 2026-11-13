import type { UseNotificationsOptions } from "@/types/features/notificationTypes";

/**
 * Canonical React Query keys for notifications.
 *
 * The list key carries every filter (status, channel_type, limit, offset) so
 * views never collide on one cache entry — the failure mode of the hand-rolled
 * unkeyed store this replaces. No count endpoint exists, so the unread badge
 * derives from the list query; add a `count(filters)` key here if one ever ships.
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
