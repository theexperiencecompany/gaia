"use client";

import { Spinner } from "@heroui/spinner";
import { useMemo } from "react";

import type {
  ModalConfig,
  NotificationRecord,
} from "@/types/features/notificationTypes";
import { groupNotificationsByTimezone } from "@/utils";

import { NotificationIcon } from "../../../components/shared/icons";
import { EnhancedNotificationCard } from "./EnhancedNotificationCard";

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

  const handleMarkAsRead = async (notificationId: string) => {
    try {
      // Only call the provided onMarkAsRead function - don't trigger additional refreshes here
      await onMarkAsRead(notificationId);
    } catch (error) {
      console.error("Error in handleMarkAsRead:", error);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto flex h-full w-full max-w-4xl items-center justify-center">
        <div className="flex flex-col items-center space-y-3">
          <Spinner size="lg" color="primary" />
          <p className="text-sm text-foreground-500">Loading notifications...</p>
        </div>
      </div>
    );
  }

  if (notifications.length === 0) {
    return (
      <div className="mx-auto mt-10 flex h-full w-full max-w-4xl items-center justify-center">
        <div className="flex flex-col items-center space-y-4 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-100/50 ring-1 ring-border-surface-800">
            <span className="text-3xl text-foreground-600">
              <NotificationIcon />
            </span>
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-white">
              {emptyMessage}
            </h3>
            <p className="text-sm text-foreground-500">{emptyDescription}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-8 px-6 py-6">
      {Object.entries(groupedNotifications).map(
        ([timeGroup, groupNotifications]) => (
          <div key={timeGroup} className="space-y-3">
            <h3 className="px-0.5 text-xs font-semibold tracking-wider text-foreground-500 uppercase">
              {timeGroup}
            </h3>
            <div className="space-y-2.5">
              {groupNotifications.map((notification) => (
                <EnhancedNotificationCard
                  key={notification.id}
                  notification={notification}
                  onMarkAsRead={handleMarkAsRead}
                  onRefresh={onRefresh}
                  onModalOpen={onModalOpen}
                />
              ))}
            </div>
          </div>
        ),
      )}
    </div>
  );
};
