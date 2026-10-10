"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import NotificationsHeader from "@/components/layout/headers/NotificationsHeader";
import { EmailPreviewModal } from "@/features/mail/components/EmailPreviewModal";
import { NotificationConnectBanner } from "@/features/notification/components/NotificationConnectBanner";
import { NotificationsList } from "@/features/notification/components/NotificationsList";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useHeader } from "@/hooks/layout/useHeader";
import {
  type ModalConfig,
  type ModalProps,
  NotificationStatus,
} from "@/types/features/notificationTypes";

const INAPP_CHANNEL = "inapp";

export default function NotificationsPage() {
  const [modalConfig, setModalConfig] = useState<ModalConfig | null>(null);
  // `props` is untyped on the wire; the component name is what makes it an EmailPreview payload.
  const modalProps = modalConfig?.props as ModalProps | undefined;
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
    if (!canMarkAllAsRead) return;
    await markAllAsRead(INAPP_CHANNEL);
  }, [canMarkAllAsRead, markAllAsRead]);

  // Keep a ref so the header's onMarkAllAsRead always calls the latest version
  // without adding handleMarkAllAsRead to the setHeader effect's dep array
  // (which would cause an infinite loop via setHeader → re-render → new callback → setHeader…)
  const handleMarkAllAsReadRef = useRef(handleMarkAllAsRead);
  useEffect(() => {
    handleMarkAllAsReadRef.current = handleMarkAllAsRead;
  });

  // Set the header with tab state
  useEffect(() => {
    setHeader(
      <NotificationsHeader
        selectedTab={selectedTab}
        onTabChange={setSelectedTab}
        unreadCount={unreadNotifications.length}
        showMarkAllAsRead={canMarkAllAsRead}
        onMarkAllAsRead={() => handleMarkAllAsReadRef.current()}
      />,
    );

    return () => {
      setHeader(null);
    };
  }, [selectedTab, unreadNotifications.length, canMarkAllAsRead, setHeader]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-primary-bg">
      <div className="shrink-0 px-6 pt-6">
        <NotificationConnectBanner variant="full" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        {selectedTab === "unread" ? (
          <NotificationsList
            notifications={unreadNotifications}
            loading={unreadLoading}
            emptyMessage="No unread notifications"
            emptyDescription="All caught up! You're up to date with everything."
            onRefresh={refreshNotifications}
            onMarkAsRead={markAsRead}
            onModalOpen={handleModalOpen}
          />
        ) : (
          <NotificationsList
            notifications={allNotifications}
            loading={allLoading}
            emptyMessage="No notifications yet"
            emptyDescription="Notifications will appear here when you receive them."
            onRefresh={refreshNotifications}
            onMarkAsRead={markAsRead}
            onModalOpen={handleModalOpen}
          />
        )}
      </div>

      {modalConfig?.component === "EmailPreviewModal" && modalProps && (
        <EmailPreviewModal
          isOpen={true}
          onClose={handleModalClose}
          subject={modalProps.subject || ""}
          body={modalProps.body || ""}
          recipients={modalProps.recipients || []}
          mode={modalProps.mode === "view" ? "view" : "edit"}
          onEmailSent={handleEmailSent}
          notificationId={modalProps.notificationId}
          actionId={modalProps.actionId}
        />
      )}
    </div>
  );
}
