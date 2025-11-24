import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { useState } from "react";
import { toast } from "sonner";

import { NotificationItem } from "@/features/notification/components/NotificationItem";
import { NotificationIcon } from "@/icons";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  type NotificationRecord,
  NotificationStatus,
} from "@/types/features/notificationTypes";

interface NotificationListSectionProps {
  notifications: NotificationRecord[];
  title?: string;
}

export default function NotificationListSection({
  notifications,
  title = "Notifications",
}: NotificationListSectionProps) {
  const [isMarkingAllRead, setIsMarkingAllRead] = useState(false);
  const [localNotifications, setLocalNotifications] = useState(notifications);

  const unreadNotifications = localNotifications.filter(
    (n) => n.status === NotificationStatus.DELIVERED,
  );

  const handleMarkAsRead = async (notificationId: string) => {
    try {
      await NotificationsAPI.markAsRead(notificationId);
      // Update local state
      setLocalNotifications((prev) =>
        prev.map((n) =>
          n.id === notificationId
            ? {
                ...n,
                status: NotificationStatus.READ,
                read_at: new Date().toISOString(),
              }
            : n,
        ),
      );
      toast.success("Notification marked as read");
    } catch (error) {
      console.error("Error marking notification as read:", error);
      toast.error("Failed to mark notification as read");
    }
  };

  const handleMarkAllAsRead = async () => {
    if (unreadNotifications.length > 0) {
      setIsMarkingAllRead(true);
      try {
        const unreadIds = unreadNotifications.map((n) => n.id);
        await NotificationsAPI.bulkMarkAsRead(unreadIds);
        // Update local state
        setLocalNotifications((prev) =>
          prev.map((n) =>
            unreadIds.includes(n.id)
              ? {
                  ...n,
                  status: NotificationStatus.READ,
                  read_at: new Date().toISOString(),
                }
              : n,
          ),
        );
        toast.success(`Marked ${unreadIds.length} notifications as read`);
      } catch (error) {
        console.error("Error marking all notifications as read:", error);
        toast.error("Failed to mark all notifications as read");
      } finally {
        setIsMarkingAllRead(false);
      }
    }
  };

  if (localNotifications.length === 0) {
    return (
      <div className="mx-auto mb-3 w-full rounded-2xl bg-zinc-800 p-3 py-0 text-white transition-all duration-300">
        <Accordion variant="light" defaultExpandedKeys={["notifications"]}>
          <AccordionItem
            key="notifications"
            aria-label="Notifications"
            title={
              <div className="flex items-center gap-3">
                <NotificationIcon className="h-5 w-5 text-zinc-400" />
                <div className="flex flex-col">
                  <span className="text-sm font-medium">{title}</span>
                </div>
              </div>
            }
          >
            <div className="flex flex-col items-center justify-center p-8 text-center">
              <NotificationIcon className="mb-4 h-10 w-10 text-zinc-600" />
              <p className="font-medium text-zinc-300">
                No notifications found
              </p>
              <p className="mt-1 text-sm text-zinc-400">
                You're all caught up! New notifications will appear here.
              </p>
            </div>
          </AccordionItem>
        </Accordion>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full rounded-2xl bg-zinc-800 p-3 py-0 text-white transition-all duration-300">
      <Accordion variant="light" defaultExpandedKeys={["notifications"]}>
        <AccordionItem
          key="notifications"
          aria-label="Notifications"
          title={
            <div className="flex items-center gap-3">
              <NotificationIcon className="h-5 w-5 text-zinc-400" />
              <div className="flex flex-col">
                <span className="text-sm font-medium">{title}</span>
              </div>
              {localNotifications.length > 0 && (
                <Chip
                  className="bg-zinc-700 text-zinc-300"
                  size="sm"
                  variant="flat"
                >
                  {localNotifications.length}
                </Chip>
              )}
              {unreadNotifications.length > 0 && (
                <Chip
                  className="bg-blue-900/30 text-blue-400"
                  size="sm"
                  variant="flat"
                >
                  {unreadNotifications.length} unread
                </Chip>
              )}
            </div>
          }
        >
          <div className="flex flex-col gap-3">
            {/* Mark All Read Button */}
            {unreadNotifications.length > 0 && (
              <div className="flex justify-end">
                <Button
                  size="sm"
                  variant="flat"
                  onPress={handleMarkAllAsRead}
                  isLoading={isMarkingAllRead}
                  className="text-zinc-300"
                >
                  Mark all read
                </Button>
              </div>
            )}

            {/* Notifications List */}
            <ScrollShadow className="max-h-[60vh]">
              <div className="space-y-2">
                {localNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    onMarkAsRead={handleMarkAsRead}
                  />
                ))}
              </div>
            </ScrollShadow>

            {/* Footer */}
            {unreadNotifications.length > 0 && (
              <div className="border-t border-zinc-700 pt-3">
                <div className="text-sm text-zinc-400">
                  {unreadNotifications.length} unread notification
                  {unreadNotifications.length !== 1 ? "s" : ""}
                </div>
              </div>
            )}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
