import type { NotificationView } from "@/types/features/notificationTypes";

import { getTimeGroup } from "./date/timezoneUtils";

/**
 * Groups notifications by dynamically calculated time periods (Today/Yesterday/Earlier) based on user's timezone
 *
 * @param {NotificationView[]} notifications - Array of notification records
 * @returns {Record<string, NotificationView[]>} Grouped notifications by time period
 *
 * @example
 * const grouped = groupNotificationsByTimezone(notifications);
 * // Returns: { "Today": [...], "Yesterday": [...], "Earlier": [...] }
 */
export const groupNotificationsByTimezone = (
  notifications: NotificationView[],
): Record<string, NotificationView[]> => {
  return notifications.reduce(
    (groups, notification) => {
      const timeGroup = getTimeGroup(notification.created_at);
      if (!groups[timeGroup]) {
        groups[timeGroup] = [];
      }
      groups[timeGroup].push(notification);
      return groups;
    },
    {} as Record<string, NotificationView[]>,
  );
};
