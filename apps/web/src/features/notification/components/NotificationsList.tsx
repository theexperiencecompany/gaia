"use client";

import { Spinner } from "@heroui/spinner";
import { useMemo } from "react";
import type {
  ModalConfig,
  NotificationRecord,
} from "@/types/features/notificationTypes";
import { groupNotificationsByTimezone } from "@/utils/notificationUtils";
import { NotificationCard } from "./NotificationCard";
import { NotificationsEmptyState } from "./NotificationsEmptyState";

interface NotificationListProps {
  notifications: NotificationRecord[];
  loading: boolean;
  emptyMessage?: string;
  emptyDescription?: string;
  onRefresh?: () => void;
  onMarkAsRead: (notificationId: string) => Promise<void>;
  onModalOpen?: (config: ModalConfig) => void;
}

export const NotificationsList = ({
  notifications,
  loading,
  emptyMessage = "No notifications",
  emptyDescription = "Notifications will appear here when you receive them.",
  onRefresh,
  onMarkAsRead,
  onModalOpen,
}: NotificationListProps) => {
  const groupedNotifications = useMemo(
    () => groupNotificationsByTimezone(notifications),
    [notifications],
  );

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner size="lg" color="primary" />
      </div>
    );
  }

  if (notifications.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <NotificationsEmptyState
          title={emptyMessage}
          description={emptyDescription}
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {Object.entries(groupedNotifications).map(
        ([timeGroup, groupNotifications]) => (
          <section key={timeGroup} className="space-y-3">
            <h3 className="px-1 text-sm font-medium text-zinc-500">
              {timeGroup}
            </h3>
            <div className="space-y-2">
              {groupNotifications.map((notification) => (
                <NotificationCard
                  key={notification.id}
                  notification={notification}
                  onMarkAsRead={onMarkAsRead}
                  onRefresh={onRefresh}
                  onModalOpen={onModalOpen}
                />
              ))}
            </div>
          </section>
        ),
      )}
    </div>
  );
};
