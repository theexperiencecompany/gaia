"use client";

import { Badge, Popover, Tabs } from "@heroui/react";
import { NotificationIcon } from "@icons";
import { useMemo, useState } from "react";
import { SidebarHeaderButton } from "@/components/layout/headers/SidebarHeaderButton";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { track } from "@/lib/analytics";
import { NotificationStatus } from "../../../types/features/notificationTypes";
import { NotificationConnectBanner } from "./NotificationConnectBanner";
import { NotificationItem } from "./NotificationItem";

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

  return (
    <div className={`relative ${className}`}>
      <Popover>
        <Popover.Trigger>
          <div className="relative">
            {/* pointer-events-none on the count lets the bell underneath
                capture hover/press; select-none keeps it from being
                text-selected. */}
            <Badge.Anchor>
              <SidebarHeaderButton
                aria-label="Notifications"
                tooltip="Notifications"
              >
                <NotificationIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-colors group-hover:text-primary" />
              </SidebarHeaderButton>
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
          </div>
        </Popover.Trigger>

        <Popover.Content className="mr-4 w-96 rounded-2xl border-1 border-zinc-700 bg-zinc-800 p-0 shadow-xl">
          <Tabs
            selectedKey={activeTab}
            onSelectionChange={(key) => setActiveTab(key as "unread" | "all")}
            variant="secondary"
            className="w-full"
          >
            <Tabs.List className="w-full">
              <Tabs.Tab id="unread">
                {/* right padding gives the corner-anchored count room so it
                    sits after the label instead of overlapping it */}
                <Badge.Anchor>
                  <span className="pr-5">Unread</span>
                  {unreadCount > 0 && (
                    <Badge
                      color="accent"
                      placement="top-right"
                      size="sm"
                      className="border-0 select-none"
                    >
                      {unreadCount > 99 ? "99+" : unreadCount}
                    </Badge>
                  )}
                </Badge.Anchor>
                <Tabs.Indicator />
              </Tabs.Tab>
              <Tabs.Tab id="all">
                All
                <Tabs.Indicator />
              </Tabs.Tab>
            </Tabs.List>
          </Tabs>

          {/* Notifications list */}
          <ScrollArea className="w-full" viewportClassName="max-h-[70vh]">
            {loading ? (
              <div className="flex items-center justify-center p-8">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-700 border-t-zinc-50" />
              </div>
            ) : filteredNotifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center p-8 text-center">
                <NotificationIcon className="mb-4 h-10 w-10 text-zinc-600" />
                <p className="font-medium text-zinc-300">
                  {activeTab === "unread"
                    ? "No unread notifications"
                    : "No notifications yet"}
                </p>
                <p className="mt-1 text-sm text-zinc-400">
                  {activeTab === "unread"
                    ? "All caught up!"
                    : "Notifications will appear here when you receive them"}
                </p>
              </div>
            ) : (
              <div className="w-full space-y-2 p-3">
                {filteredNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    onMarkAsRead={handleMarkAsRead}
                  />
                ))}
              </div>
            )}
          </ScrollArea>

          <NotificationConnectBanner variant="compact" />

          {/* Footer */}
          {canMarkAllAsRead && (
            <div className="flex w-full items-center justify-evenly gap-3 p-3">
              <GaiaButton
                variant="default-solid"
                size="sm"
                fullWidth
                onPress={handleMarkAllAsRead}
                isPending={isMarkingAllRead}
                isDisabled={isMarkingAllRead}
              >
                Mark all as read
              </GaiaButton>
            </div>
          )}
        </Popover.Content>
      </Popover>
    </div>
  );
}
