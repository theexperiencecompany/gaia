"use client";

import { Button } from "@heroui/button";
import { Tab, Tabs } from "@heroui/tabs";
import { CheckmarkCircle02Icon } from "@icons";
import { useCallback, useEffect, useState } from "react";
import NotificationsHeader from "@/components/layout/headers/NotificationsHeader";
import { EmailPreviewModal } from "@/features/mail/components/EmailPreviewModal";
import { NotificationConnectBanner } from "@/features/notification/components/NotificationConnectBanner";
import { NotificationsList } from "@/features/notification/components/NotificationsList";
import { UnreadCountChip } from "@/features/notification/components/UnreadCountChip";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useHeader } from "@/hooks/layout/useHeader";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  type ModalConfig,
  NotificationStatus,
} from "@/types/features/notificationTypes";

export default function NotificationsPage() {
  const [modalConfig, setModalConfig] = useState<ModalConfig | null>(null);
  const [selectedTab, setSelectedTab] = useState<string>("unread");
  const { setHeader } = useHeader();

  // Get unread notifications
  const {
    notifications: unreadNotifications,
    loading: unreadLoading,
    refetch: refetchUnread,
  } = useNotifications({
    status: NotificationStatus.DELIVERED,
    limit: 100,
    channel_type: "inapp",
  });

  // Get all notifications data
  const {
    notifications: allNotifications,
    loading: allLoading,
    refetch: refetchAll,
  } = useNotifications({
    limit: 100,
    channel_type: "inapp",
  });

  // Simple mark as read that refreshes both lists
  const handleMarkAsRead = async (notificationId: string) => {
    try {
      await NotificationsAPI.markAsRead(notificationId);
      // Refresh both lists in parallel after marking as read
      await Promise.all([refetchUnread(), refetchAll()]);
    } catch (error) {
      console.error("Error marking notification as read:", error);
    }
  };

  // Simple refresh function
  const refreshNotifications = useCallback(async () => {
    await Promise.all([refetchAll(), refetchUnread()]);
  }, [refetchAll, refetchUnread]);

  // Handle modal opening from notification actions
  const handleModalOpen = (config: ModalConfig) => {
    setModalConfig(config);
  };

  // Handle modal closing
  const handleModalClose = () => {
    setModalConfig(null);
  };

  // Handle email sent callback to refresh notifications
  const handleEmailSent = () => {
    // Refresh notifications after email is sent
    refreshNotifications();
  };

  const handleMarkAllAsRead = useCallback(async () => {
    const notificationIds = unreadNotifications.map((n) => n.id);
    try {
      if (notificationIds.length === 0) {
        toast.error("No notifications to mark as read");
        return;
      }
      await NotificationsAPI.bulkMarkAsRead(notificationIds);
      // Refresh both lists in parallel
      await Promise.all([refetchUnread(), refetchAll()]);
    } catch (error) {
      console.error("Error marking notification as read:", error);
    }
  }, [unreadNotifications, refetchUnread, refetchAll]);

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

            {unreadNotifications.length > 0 && (
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
            onMarkAsRead={handleMarkAsRead}
            onModalOpen={handleModalOpen}
          />
        </div>
      </div>

      {modalConfig?.component === "EmailPreviewModal" && modalConfig.props && (
        <EmailPreviewModal
          isOpen={true}
          onClose={handleModalClose}
          subject={modalConfig.props.subject || ""}
          body={modalConfig.props.body || ""}
          recipients={modalConfig.props.recipients || []}
          mode={modalConfig.props.mode === "view" ? "view" : "edit"}
          onEmailSent={handleEmailSent}
          notificationId={modalConfig.props.notificationId}
          actionId={modalConfig.props.actionId}
        />
      )}
    </div>
  );
}
