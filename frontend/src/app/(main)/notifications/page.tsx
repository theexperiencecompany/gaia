"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import NotificationsHeader from "@/components/layout/headers/NotificationsHeader";
import { EmailPreviewModal } from "@/features/mail/components/EmailPreviewModal";
import { NotificationsList } from "@/features/notification/components/NotificationsList";
import { useAllNotifications } from "@/features/notification/hooks/useAllNotifications";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useHeader } from "@/hooks/layout/useHeader";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  ModalConfig,
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

  const handleBulkMarkAsRead = useCallback(
    async (notificationIds: string[]) => {
      try {
        if (notificationIds.length == 0)
          return toast.error("No events to mark as read");
        await NotificationsAPI.bulkMarkAsRead(notificationIds);
        await refetchUnread();
        await refetchAll();
      } catch (error) {
        console.error("Error marking notification as read:", error);
      }
    },
    [refetchUnread, refetchAll],
  );

  // Simple refresh function
  const refreshNotifications = useCallback(async () => {
    await refetchAll();
    await refetchUnread();
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

  // Memoize the mark all as read handler to prevent recreating it on every render
  const handleMarkAllAsRead = useCallback(async () => {
    await handleBulkMarkAsRead(unreadNotifications.map((n) => n.id));
  }, [unreadNotifications, handleBulkMarkAsRead]);

  // Set the header with tab state
  useEffect(() => {
    setHeader(
      <NotificationsHeader
        selectedTab={selectedTab}
        onTabChange={setSelectedTab}
        unreadCount={unreadNotifications.length}
        onMarkAllAsRead={handleMarkAllAsRead}
      />,
    );

    return () => {
      setHeader(null);
    };
  }, [selectedTab, unreadNotifications.length, handleMarkAllAsRead, setHeader]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-[#1a1a1a]">
      <div className="max-h-[calc(100vh-120px)] overflow-y-auto px-6 pt-6">
        {selectedTab === "unread" ? (
          <NotificationsList
            notifications={unreadNotifications}
            loading={unreadLoading}
            emptyMessage="No unread notifications"
            emptyDescription="All caught up! You're up to date with everything."
            onRefresh={refreshNotifications}
            onMarkAsRead={handleMarkAsRead}
            onModalOpen={handleModalOpen}
          />
        ) : (
          <NotificationsList
            notifications={allNotifications}
            loading={allLoading}
            emptyMessage="No notifications yet"
            emptyDescription="Notifications will appear here when you receive them."
            onRefresh={refreshNotifications}
            onMarkAsRead={handleMarkAsRead}
            onModalOpen={handleModalOpen}
          />
        )}
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
