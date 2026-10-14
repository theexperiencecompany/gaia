"use client";

import { Button } from "@heroui/button";
import { Tab, Tabs } from "@heroui/tabs";
import { CheckmarkCircle02Icon } from "@icons";
import { useCallback, useEffect, useState } from "react";
import NotificationsHeader from "@/components/layout/headers/NotificationsHeader";
import { NotificationConnectBanner } from "@/features/notification/components/NotificationConnectBanner";
import { NotificationModalHost } from "@/features/notification/components/NotificationModalHost";
import { NotificationsList } from "@/features/notification/components/NotificationsList";
import { UnreadCountChip } from "@/features/notification/components/UnreadCountChip";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useHeader } from "@/hooks/layout/useHeader";
import {
  type ModalConfig,
  NotificationStatus,
} from "@/types/features/notificationTypes";

const INAPP_CHANNEL = "inapp";

export default function NotificationsPage() {
  const [modalConfig, setModalConfig] = useState<ModalConfig | null>(null);
  const [selectedTab, setSelectedTab] = useState<string>("unread");
  const { setHeader } = useHeader();

  // Both views read the same store entry, so this is a single fetch.
  const {
    notifications: unreadNotifications,
    loading: unreadLoading,
    refetch: refreshNotifications,
    markAsRead,
    markAllAsRead,
    hasMoreUnseen,
  } = useNotifications({
    status: NotificationStatus.DELIVERED,
    limit: 100,
    channel_type: INAPP_CHANNEL,
  });

  // The loaded page can undercount unread notifications, so a button gated on
  // it alone could hide even though an older delivered notification exists.
  const canMarkAllAsRead = unreadNotifications.length > 0 || hasMoreUnseen;

  const { notifications: allNotifications, loading: allLoading } =
    useNotifications({
      limit: 100,
      channel_type: INAPP_CHANNEL,
    });

  const handleModalOpen = (config: ModalConfig) => {
    setModalConfig(config);
  };

  const handleModalClose = () => {
    setModalConfig(null);
  };

  const handleEmailSent = () => {
    refreshNotifications();
  };

  const handleMarkAllAsRead = useCallback(async () => {
    if (!canMarkAllAsRead) return;
    await markAllAsRead(INAPP_CHANNEL);
  }, [canMarkAllAsRead, markAllAsRead]);

  useEffect(() => {
    setHeader(<NotificationsHeader />);
    return () => {
      setHeader(null);
    };
  }, [setHeader]);

  const isUnreadTab = selectedTab === "unread";

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-primary-bg">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-5 px-6 py-6">
          <NotificationConnectBanner variant="full" />

          <div className="flex items-center justify-between">
            <Tabs
              aria-label="Notifications"
              selectedKey={selectedTab}
              onSelectionChange={(key) => setSelectedTab(key as string)}
            >
              <Tab
                key="unread"
                title={
                  <div className="flex items-center gap-1.5">
                    <span>Unread</span>
                    <UnreadCountChip count={unreadNotifications.length} />
                  </div>
                }
              />
              <Tab key="all" title="All" />
            </Tabs>

            {canMarkAllAsRead && (
              <Button
                size="sm"
                variant="light"
                className="text-zinc-400"
                startContent={<CheckmarkCircle02Icon className="size-4" />}
                onPress={handleMarkAllAsRead}
              >
                Mark all as read
              </Button>
            )}
          </div>

          <NotificationsList
            notifications={isUnreadTab ? unreadNotifications : allNotifications}
            loading={isUnreadTab ? unreadLoading : allLoading}
            emptyMessage={
              isUnreadTab ? "No unread notifications" : "No notifications yet"
            }
            emptyDescription={
              isUnreadTab
                ? "All caught up! You're up to date with everything."
                : "Notifications will appear here when you receive them."
            }
            onRefresh={refreshNotifications}
            onMarkAsRead={markAsRead}
            onModalOpen={handleModalOpen}
          />
        </div>
      </div>

      <NotificationModalHost
        config={modalConfig}
        onClose={handleModalClose}
        onEmailSent={handleEmailSent}
      />
    </div>
  );
}
