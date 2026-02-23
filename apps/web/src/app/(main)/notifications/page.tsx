"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import NotificationsHeader from "@/components/layout/headers/NotificationsHeader";
import { EmailPreviewModal } from "@/features/mail/components/EmailPreviewModal";
import { NotificationConnectBanner } from "@/features/notification/components/NotificationConnectBanner";
import { NotificationsList } from "@/features/notification/components/NotificationsList";
import { useAllNotifications } from "@/features/notification/hooks/useAllNotifications";
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
        if (notificationIds.length === 0)
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

  const handleMarkAllAsRead = useCallback(async () => {
    await handleBulkMarkAsRead(unreadNotifications.map((n) => n.id));
  }, [unreadNotifications, handleBulkMarkAsRead]);

  // Keep a ref so the header's onMarkAllAsRead always calls the latest version
  // without adding handleMarkAllAsRead to the setHeader effect's dep array
  // (which would cause an infinite loop via setHeader → re-render → new callback → setHeader…)
  const handleMarkAllAsReadRef = useRef(handleMarkAllAsRead);
  handleMarkAllAsReadRef.current = handleMarkAllAsRead;

  // Set the header with tab state
  useEffect(() => {
    setHeader(
      <NotificationsHeader
        selectedTab={selectedTab}
        onTabChange={setSelectedTab}
        unreadCount={unreadNotifications.length}
        onMarkAllAsRead={() => handleMarkAllAsReadRef.current()}
      />,
    );

    return () => {
      setHeader(null);
    };
  }, [selectedTab, unreadNotifications.length, setHeader]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-primary-bg">
      <div className="max-h-[calc(100vh-120px)] overflow-y-auto px-6 pt-6">
        <NotificationConnectBanner variant="full" />
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
