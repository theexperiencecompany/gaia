"use client";

import { Badge } from "@heroui/badge";
import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Tab, Tabs } from "@heroui/tabs";
import { NotificationIcon } from "@icons";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { SidebarHeaderButton } from "@/components/layout/headers/HeaderManager";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
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
  const router = useRouter();

  const notificationOptions = useMemo(
    () => ({
      status: activeTab === "unread" ? NotificationStatus.DELIVERED : undefined,
      limit: 50,
    }),
    [activeTab],
  );

  const { notifications, unreadCount, loading, markAsRead, bulkMarkAsRead } =
    useNotifications(notificationOptions);

  const handleMarkAsRead = async (notificationId: string) => {
    await markAsRead(notificationId);
  };

  const handleMarkAllAsRead = async () => {
    const unreadIds = notifications
      .filter((n) => n.status === NotificationStatus.DELIVERED)
      .map((n) => n.id);
    if (unreadIds.length === 0) return;
    setIsMarkingAllRead(true);
    try {
      await bulkMarkAsRead(unreadIds);
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
        <PopoverTrigger>
          <div className="relative">
            <Badge
              color="primary"
              shape="circle"
              size="sm"
              content={unreadCount > 99 ? "99+" : unreadCount}
              isInvisible={unreadCount === 0}
              // pointer-events-none lets the bell underneath capture hover/press;
              // select-none keeps the count from being text-selected.
              classNames={{ badge: "pointer-events-none select-none border-0" }}
            >
              <SidebarHeaderButton
                aria-label="Notifications"
                tooltip="Notifications"
              >
                <NotificationIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
              </SidebarHeaderButton>
            </Badge>
          </div>
        </PopoverTrigger>

        <PopoverContent className="mr-4 w-96 rounded-2xl border-1 border-zinc-700 bg-zinc-800 p-0 shadow-xl">
          <Tabs
            selectedKey={activeTab}
            onSelectionChange={(key) => setActiveTab(key as "unread" | "all")}
            variant="underlined"
            fullWidth
          >
            <Tab
              key="unread"
              title={
                <Badge
                  color="primary"
                  size="sm"
                  placement="top-right"
                  content={unreadCount > 99 ? "99+" : unreadCount}
                  isInvisible={unreadCount === 0}
                  classNames={{ badge: "select-none border-0" }}
                >
                  {/* right padding gives the corner-anchored count room so it
                      sits after the label instead of overlapping it */}
                  <span className="pr-5">Unread</span>
                </Badge>
              }
            />
            <Tab key="all" title="All" />
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
          <div className="flex w-full items-center justify-evenly gap-3 p-3">
            {unreadCount > 0 && (
              <Button
                size="sm"
                fullWidth
                onPress={handleMarkAllAsRead}
                isLoading={isMarkingAllRead}
                isDisabled={isMarkingAllRead}
              >
                Mark all as read
              </Button>
            )}

            <Button
              fullWidth
              size="sm"
              variant={unreadCount > 0 ? "bordered" : "solid"}
              onPress={() => {
                router.push("/notifications");
              }}
            >
              View all notifications
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
