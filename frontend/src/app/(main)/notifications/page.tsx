"use client";

import { Tab, Tabs } from "@heroui/tabs";
import { useState } from "react";
import { toast } from "sonner";

import { EmailPreviewModal } from "@/features/mail/components/EmailPreviewModal";
import { NotificationsList } from "@/features/notification/components/NotificationsList";
import { useAllNotifications } from "@/features/notification/hooks/useAllNotifications";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  ModalConfig,
  NotificationStatus,
} from "@/types/features/notificationTypes";
import { Button } from "@heroui/button";

export default function NotificationsPage() {
  const [modalConfig, setModalConfig] = useState<ModalConfig | null>(null);

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
    allNotifications,
    loading: allLoading,
    refetchAll,
  } = useAllNotifications({
    limit: 100,
    channel_type: "inapp",
  });

  // Simple mark as read that refreshes both lists
  const handleMarkAsRead = async (notificationId: string) => {
    try {
      await NotificationsAPI.markAsRead(notificationId);
      // Refresh both lists after marking as read
      await refetchUnread();
      await refetchAll();
    } catch (error) {
      console.error("Error marking notification as read:", error);
    }
  };

  const handleBulkMarkAsRead = async (notificationIds: string[]) => {
    try {
      if (notificationIds.length == 0)
        return toast.error("No events to mark as read");
      await NotificationsAPI.bulkMarkAsRead(notificationIds);
      // Refresh both lists after marking as read
      await refetchUnread();
      await refetchAll();
    } catch (error) {
      console.error("Error marking notification as read:", error);
    }
  };

  // Simple refresh function
  const refreshNotifications = async () => {
    await refetchAll();
    await refetchUnread();
  };

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

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-[#1a1a1a]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            Notifications
          </h1>
          <p className="mt-0.5 text-sm text-zinc-500">
            Stay updated with your latest activity
          </p>
        </div>
        {unreadNotifications.length > 0 && (
          <Button
            size="sm"
            variant={"flat"}
            onPress={async () => {
              await handleBulkMarkAsRead(unreadNotifications.map((n) => n.id));
            }}
          >
            Mark All as Read
          </Button>
        )}
      </div>

      <Tabs
        aria-label="Notifications"
        fullWidth
        className="mx-auto mt-3 max-w-3xl"
      >
        <Tab
          key="unread"
          title={
            <div className="flex items-center gap-2">
              <span>Unread</span>
              {unreadNotifications.length > 0 && (
                <span className="ml-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/10 px-1.5 text-xs font-semibold text-primary">
                  {unreadNotifications.length > 99
                    ? "99+"
                    : unreadNotifications.length}
                </span>
              )}
            </div>
          }
        >
          <div className="max-h-[calc(100vh-200px)] overflow-y-auto">
            <NotificationsList
              notifications={unreadNotifications}
              loading={unreadLoading}
              emptyMessage="No unread notifications"
              emptyDescription="All caught up! You're up to date with everything."
              onRefresh={refreshNotifications}
              onMarkAsRead={handleMarkAsRead}
              onModalOpen={handleModalOpen}
            />
          </div>
        </Tab>
        <Tab key="all" title="All">
          <div className="max-h-[calc(100vh-200px)] overflow-y-auto">
            <NotificationsList
              notifications={allNotifications}
              loading={allLoading}
              emptyMessage="No notifications yet"
              emptyDescription="Notifications will appear here when you receive them."
              onRefresh={refreshNotifications}
              onMarkAsRead={handleMarkAsRead}
              onModalOpen={handleModalOpen}
            />
          </div>
        </Tab>
      </Tabs>

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
