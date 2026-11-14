"use client";

import { Badge } from "@heroui/badge";
import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Spinner } from "@heroui/spinner";
import { Tab, Tabs } from "@heroui/tabs";
import { NotificationIcon } from "@icons";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { SidebarHeaderButton } from "@/components/layout/headers/SidebarHeaderButton";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { track } from "@/lib/analytics";
import {
  type ModalConfig,
  NotificationStatus,
} from "../../../types/features/notificationTypes";
import { NotificationCard } from "./NotificationCard";
import { NotificationConnectBanner } from "./NotificationConnectBanner";
import { NotificationModalHost } from "./NotificationModalHost";
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
  const [modalConfig, setModalConfig] = useState<ModalConfig | null>(null);
  const router = useRouter();

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
                <NotificationIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-colors group-hover:text-primary" />
              </SidebarHeaderButton>
            </Badge>
          </div>
        </PopoverTrigger>

        <PopoverContent className="mr-4 w-96 rounded-2xl bg-zinc-900 p-0 shadow-xl">
          {/* Header: tabs + mark all as read */}
          <div className="flex w-full items-center justify-between px-3 pt-3">
            <Tabs
              aria-label="Notifications"
              size="sm"
              selectedKey={activeTab}
              onSelectionChange={(key) => setActiveTab(key as "unread" | "all")}
            >
              <Tab
                key="unread"
                title={
                  <div className="flex items-center gap-1.5">
                    <span>Unread</span>
                    <UnreadCountChip count={unreadCount} />
                  </div>
                }
              />
              <Tab key="all" title="All" />
            </Tabs>

            {canMarkAllAsRead && (
              <Button
                size="sm"
                variant="light"
                className="text-xs text-zinc-400"
                onPress={handleMarkAllAsRead}
                isLoading={isMarkingAllRead}
              >
                Mark all as read
              </Button>
            )}
          </div>

          {/* Notifications list */}
          <div className="max-h-[60vh] w-full overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center p-10">
                <Spinner size="sm" color="primary" />
              </div>
            ) : filteredNotifications.length === 0 ? (
              <div className="flex items-center justify-center p-10">
                <NotificationsEmptyState
                  title={
                    activeTab === "unread"
                      ? "No unread notifications"
                      : "No notifications yet"
                  }
                  description={
                    activeTab === "unread"
                      ? "All caught up!"
                      : "Notifications will appear here when you receive them."
                  }
                />
              </div>
            ) : (
              <div className="w-full space-y-2 p-3">
                {filteredNotifications.map((notification) => (
                  <NotificationCard
                    key={notification.id}
                    notification={notification}
                    clampBody
                    onMarkAsRead={handleMarkAsRead}
                    onModalOpen={setModalConfig}
                    onRefresh={refetch}
                  />
                ))}
              </div>
            )}
          </div>

          <NotificationConnectBanner variant="compact" />

          {/* Footer */}
          <div className="w-full p-3">
            <Button
              fullWidth
              size="sm"
              variant="flat"
              onPress={() => {
                router.push("/notifications");
              }}
            >
              View all notifications
            </Button>
          </div>
        </PopoverContent>
      </Popover>

      <NotificationModalHost
        config={modalConfig}
        onClose={() => setModalConfig(null)}
        onEmailSent={refetch}
      />
    </div>
  );
}
