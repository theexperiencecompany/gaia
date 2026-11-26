"use client";

import { Badge, Popover, Spinner, Tabs, Tooltip } from "@heroui/react";
import { NotificationIcon } from "@icons";
import { formatDay } from "@shared/utils";
import { useMemo, useState } from "react";
import { overlayVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { track } from "@/lib/analytics";
import { NotificationStatus } from "../../../types/features/notificationTypes";
import { NotificationCard } from "./NotificationCard";
import { NotificationConnectBanner } from "./NotificationConnectBanner";
import { NotificationsEmptyState } from "./NotificationsEmptyState";
import { UnreadCountChip } from "./UnreadCountChip";

interface NotificationCenterProps {
  className?: string;
}

export function NotificationCenter({
  className = "",
}: NotificationCenterProps) {
  const [activeTab, setActiveTab] = useState<"unread" | "all">("unread");
  const [isMarkingAllRead, setIsMarkingAllRead] = useState(false);

  const notificationOptions = useMemo(
    () => ({
      status: activeTab === "unread" ? NotificationStatus.DELIVERED : undefined,
      limit: 50,
    }),
    [activeTab],
  );

  const {
    notifications,
    unreadCount,
    hasMoreUnseen,
    loading,
    markAsRead,
    markAllAsRead,
    refetch,
  } = useNotifications(notificationOptions);

  // The loaded page can undercount unread notifications, so gating on
  // unreadCount alone could hide the button even though an older delivered
  // notification exists beyond what's loaded.
  const canMarkAllAsRead = unreadCount > 0 || hasMoreUnseen;

  const handleMarkAsRead = async (notificationId: string) => {
    track("notification:viewed", {
      notification_id: notificationId,
      source: "popover",
    });
    await markAsRead(notificationId);
  };

  const handleMarkAllAsRead = async () => {
    if (!canMarkAllAsRead) return;
    setIsMarkingAllRead(true);
    try {
      await markAllAsRead();
    } finally {
      setIsMarkingAllRead(false);
    }
  };

  const filteredNotifications =
    activeTab === "unread"
      ? notifications.filter((n) => n.status === NotificationStatus.DELIVERED)
      : notifications;

  const notificationsByDay = new Map<string, typeof filteredNotifications>();
  for (const notification of filteredNotifications) {
    const day = formatDay(notification.created_at);
    notificationsByDay.set(day, [
      ...(notificationsByDay.get(day) ?? []),
      notification,
    ]);
  }

  return (
    <div className={`relative ${className}`}>
      <Popover>
        {/* The bell is the popover's trigger itself: wrapped in Popover.Trigger it
            would be a second button with its own tab stop. */}
        <Tooltip>
          <GaiaButton
            isIconOnly
            variant="ghost"
            aria-label="Notifications"
            tone="muted"
            hoverTone="accent"
          >
            {/* pointer-events-none on the count lets the bell underneath
                capture hover/press; select-none keeps it from being
                text-selected. */}
            <Badge.Anchor>
              <NotificationIcon className="min-h-[20px] min-w-[20px]" />
              {unreadCount > 0 && (
                <Badge
                  color="accent"
                  placement="top-right"
                  size="sm"
                  className="pointer-events-none border-0 select-none"
                >
                  {unreadCount > 99 ? "99+" : unreadCount}
                </Badge>
              )}
            </Badge.Anchor>
          </GaiaButton>
          <Tooltip.Content>Notifications</Tooltip.Content>
        </Tooltip>

        <Popover.Content
          className={overlayVariants({
            surface: "raised",
            className: "mr-4 w-96 shadow-xl",
          })}
        >
          <div className="flex w-full items-center justify-between gap-2 px-3 pt-2">
            <Tabs
              selectedKey={activeTab}
              onSelectionChange={(key) => setActiveTab(key as "unread" | "all")}
              variant="secondary"
            >
              <Tabs.List>
                <Tabs.Tab id="unread">
                  <div className="flex items-center gap-1.5">
                    <span>Unread</span>
                    <UnreadCountChip count={unreadCount} />
                  </div>
                  <Tabs.Indicator />
                </Tabs.Tab>
                <Tabs.Tab id="all">
                  All
                  <Tabs.Indicator />
                </Tabs.Tab>
              </Tabs.List>
            </Tabs>

            {canMarkAllAsRead && (
              <GaiaButton
                size="sm"
                variant="ghost"
                tone="muted"
                className="shrink-0 text-xs"
                onPress={handleMarkAllAsRead}
                isPending={isMarkingAllRead}
              >
                Mark all as read
              </GaiaButton>
            )}
          </div>

          <ScrollArea className="w-full" viewportClassName="max-h-[60vh]">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Spinner size="sm" color="accent" />
              </div>
            ) : filteredNotifications.length === 0 ? (
              <div className="flex items-center justify-center px-6 py-12">
                <NotificationsEmptyState
                  title={
                    activeTab === "unread"
                      ? "No unread notifications"
                      : "No notifications yet"
                  }
                  description={
                    activeTab === "unread"
                      ? "You're all caught up."
                      : "New notifications will show up here."
                  }
                />
              </div>
            ) : (
              <div className="flex w-full flex-col gap-4 p-3">
                {[...notificationsByDay].map(([day, group]) => (
                  <section key={day} className="flex flex-col gap-2">
                    <h2 className="px-1 text-xs font-medium text-zinc-500">
                      {day}
                    </h2>
                    {group.map((notification) => (
                      <NotificationCard
                        key={notification.id}
                        notification={notification}
                        tone="inset"
                        clampBody
                        onMarkAsRead={handleMarkAsRead}
                        onRefresh={refetch}
                      />
                    ))}
                  </section>
                ))}
              </div>
            )}
          </ScrollArea>

          <div className="pb-3">
            <NotificationConnectBanner variant="compact" />
          </div>
        </Popover.Content>
      </Popover>
    </div>
  );
}
