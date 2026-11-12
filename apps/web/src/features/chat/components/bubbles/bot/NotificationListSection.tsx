import { Accordion, AccordionItem, Chip, ScrollShadow } from "@heroui/react";
import { NotificationIcon } from "@icons";
import { useMemo, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { NotificationItem } from "@/features/notification/components/NotificationItem";
import {
  ACCORDION_INDICATOR,
  ACCORDION_PANEL,
  ACCORDION_ROOT,
  ACCORDION_TRIGGER,
} from "@/lib/heroui/accordionParity";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  NotificationStatus,
  type NotificationView,
} from "@/types/features/notificationTypes";

interface NotificationListSectionProps {
  notifications: NotificationView[];
  title?: string;
}

// Optimistic read-state overlay keyed by notification id, applied on top of the
// incoming prop so fresh notifications from the parent still show up after a
// local mark-as-read (instead of being hidden behind a stale copied array).
interface ReadUpdate {
  status: NotificationStatus.READ;
  read_at: string;
}

export default function NotificationListSection({
  notifications,
  title = "Notifications",
}: NotificationListSectionProps) {
  const [isMarkingAllRead, setIsMarkingAllRead] = useState(false);
  const [readUpdates, setReadUpdates] = useState<Record<string, ReadUpdate>>(
    {},
  );

  const localNotifications = useMemo(
    () =>
      notifications.map((n) => {
        const update = readUpdates[n.id];
        return update ? { ...n, ...update } : n;
      }),
    [notifications, readUpdates],
  );

  const unreadNotifications = localNotifications.filter(
    (n) => n.status === NotificationStatus.DELIVERED,
  );

  const handleMarkAsRead = async (notificationId: string) => {
    try {
      await NotificationsAPI.markAsRead(notificationId);
      // Update local state
      setReadUpdates((prev) => ({
        ...prev,
        [notificationId]: {
          status: NotificationStatus.READ,
          read_at: new Date().toISOString(),
        },
      }));
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
        const unreadIdSet = new Set(unreadIds);
        await NotificationsAPI.bulkMarkAsRead(unreadIds);
        // Update local state
        const readAt = new Date().toISOString();
        setReadUpdates((prev) => {
          const next = { ...prev };
          for (const id of unreadIdSet) {
            next[id] = { status: NotificationStatus.READ, read_at: readAt };
          }
          return next;
        });
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
      <div className="mx-auto mb-3 w-full rounded-2xl bg-zinc-800 p-3 py-0 text-white transition-colors duration-300">
        <Accordion
          className={ACCORDION_ROOT}
          defaultExpandedKeys={["notifications"]}
        >
          <AccordionItem id="notifications">
            <Accordion.Heading>
              <Accordion.Trigger className={ACCORDION_TRIGGER}>
                <div className="flex items-center gap-3">
                  <NotificationIcon className="h-5 w-5 text-zinc-400" />
                  <div className="flex flex-col">
                    <span className="text-sm font-medium">{title}</span>
                  </div>
                </div>
                <Accordion.Indicator className={ACCORDION_INDICATOR} />
              </Accordion.Trigger>
            </Accordion.Heading>
            <Accordion.Panel className={ACCORDION_PANEL}>
              <div className="flex flex-col items-center justify-center p-8 text-center">
                <NotificationIcon className="mb-4 h-10 w-10 text-zinc-600" />
                <p className="font-medium text-zinc-300">
                  No notifications found
                </p>
                <p className="mt-1 text-sm text-zinc-400">
                  You're all caught up! New notifications will appear here.
                </p>
              </div>
            </Accordion.Panel>
          </AccordionItem>
        </Accordion>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full rounded-2xl bg-zinc-800 p-3 py-0 text-white transition-colors duration-300">
      <Accordion
        className={ACCORDION_ROOT}
        defaultExpandedKeys={["notifications"]}
      >
        <AccordionItem id="notifications">
          <Accordion.Heading>
            <Accordion.Trigger className={ACCORDION_TRIGGER}>
              <div className="flex items-center gap-3">
                <NotificationIcon className="h-5 w-5 text-zinc-400" />
                <div className="flex flex-col">
                  <span className="text-sm font-medium">{title}</span>
                </div>
                {localNotifications.length > 0 && (
                  <Chip
                    className="bg-zinc-700 text-zinc-300"
                    size="sm"
                    variant="soft"
                  >
                    {localNotifications.length}
                  </Chip>
                )}
                {unreadNotifications.length > 0 && (
                  <Chip
                    className="bg-blue-900/30 text-blue-400"
                    size="sm"
                    variant="soft"
                  >
                    {unreadNotifications.length} unread
                  </Chip>
                )}
              </div>
              <Accordion.Indicator className={ACCORDION_INDICATOR} />
            </Accordion.Trigger>
          </Accordion.Heading>
          <Accordion.Panel className={ACCORDION_PANEL}>
            <div className="flex flex-col gap-3">
              {/* Mark All Read Button */}
              {unreadNotifications.length > 0 && (
                <div className="flex justify-end">
                  <GaiaButton
                    size="sm"
                    variant="default-soft"
                    onPress={handleMarkAllAsRead}
                    isPending={isMarkingAllRead}
                    className="text-zinc-300"
                  >
                    Mark all read
                  </GaiaButton>
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
          </Accordion.Panel>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
