import { useRef, useState } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  Cancel01Icon,
  Delete02Icon,
  FolderIcon,
  Settings01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  NotificationConnectBanner,
  NotificationsList,
  useInappNotifications,
  useNotificationActions,
} from "@/features/notifications";
import type { NotificationPreferencesSheetRef } from "@/features/notifications/components/NotificationPreferencesSheet";
import { NotificationPreferencesSheet } from "@/features/notifications/components/NotificationPreferencesSheet";
import type {
  InAppNotification,
  InAppNotificationAction,
} from "@/features/notifications/types/inapp-notification-types";
import { useResponsive } from "@/lib/responsive";

type NotificationsTab = "unread" | "all" | "archived";

const TABS: { key: NotificationsTab; label: string }[] = [
  { key: "unread", label: "Unread" },
  { key: "all", label: "All" },
  { key: "archived", label: "Archived" },
];

export default function NotificationsScreen() {
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [activeTab, setActiveTab] = useState<NotificationsTab>("unread");
  const [isSelectMode, setIsSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const prefsSheetRef = useRef<NotificationPreferencesSheetRef>(null);

  const {
    unreadNotifications,
    allNotifications,
    archivedNotifications,
    isLoading,
    isRefreshing,
    error,
    refetch,
    markAsRead,
    markAllAsRead,
    archiveNotification,
    bulkMarkRead,
    bulkArchive,
    bulkDelete,
    isMarkingAsRead,
    isMarkingAllAsRead,
  } = useInappNotifications();
  const { executeNotificationAction, isActionLoading } =
    useNotificationActions();

  const notifications =
    activeTab === "unread"
      ? unreadNotifications
      : activeTab === "archived"
        ? archivedNotifications
        : allNotifications;

  const handleMarkAllAsRead = async () => {
    await markAllAsRead(unreadNotifications.map((item) => item.id));
  };

  const handleLongPress = (notificationId: string) => {
    setIsSelectMode(true);
    setSelectedIds(new Set([notificationId]));
  };

  const handleSelectToggle = (notificationId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(notificationId)) {
        next.delete(notificationId);
      } else {
        next.add(notificationId);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    setSelectedIds(new Set(notifications.map((n) => n.id)));
  };

  const handleCancelSelect = () => {
    setIsSelectMode(false);
    setSelectedIds(new Set());
  };

  const handleBulkMarkRead = async () => {
    const ids = Array.from(selectedIds);
    await bulkMarkRead(ids);
    handleCancelSelect();
  };

  const handleBulkArchive = async () => {
    const ids = Array.from(selectedIds);
    await bulkArchive(ids);
    handleCancelSelect();
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    await bulkDelete(ids);
    handleCancelSelect();
  };

  const tabCounts: Record<NotificationsTab, number> = {
    unread: unreadNotifications.length,
    all: allNotifications.length,
    archived: archivedNotifications.length,
  };

  return (
    <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          gap: spacing.md,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          {isSelectMode ? (
            <>
              <Pressable
                onPress={handleCancelSelect}
                style={{ marginRight: spacing.sm }}
              >
                <AppIcon icon={Cancel01Icon} size={20} color="#8e8e93" />
              </Pressable>
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#fff",
                }}
              >
                {selectedIds.size} selected
              </Text>
              <View style={{ flex: 1 }} />
              <Pressable
                onPress={handleSelectAll}
                style={{
                  backgroundColor: "rgba(0,187,255,0.1)",
                  borderRadius: 8,
                  paddingHorizontal: spacing.md,
                  paddingVertical: 6,
                }}
              >
                <Text
                  style={{
                    color: "#16c1ff",
                    fontSize: fontSize.xs,
                    fontWeight: "500",
                  }}
                >
                  Select All
                </Text>
              </Pressable>
            </>
          ) : (
            <>
              <Text
                style={{
                  fontSize: fontSize.lg,
                  fontWeight: "600",
                  color: "#fff",
                }}
              >
                Notifications
              </Text>

              <View style={{ flex: 1 }} />

              <Pressable
                onPress={() => prefsSheetRef.current?.open()}
                style={{ marginRight: spacing.sm, opacity: 0.7 }}
              >
                <AppIcon icon={Settings01Icon} size={20} color="#8e8e93" />
              </Pressable>

              {unreadNotifications.length > 0 && (
                <Pressable
                  disabled={isMarkingAllAsRead}
                  onPress={() => {
                    void handleMarkAllAsRead();
                  }}
                  style={{
                    opacity: isMarkingAllAsRead ? 0.5 : 1,
                    backgroundColor: "rgba(22,193,255,0.1)",
                    borderRadius: 8,
                    paddingHorizontal: spacing.md,
                    paddingVertical: 6,
                  }}
                >
                  <Text
                    style={{
                      color: "#16c1ff",
                      fontSize: fontSize.xs,
                      fontWeight: "500",
                    }}
                  >
                    {isMarkingAllAsRead ? "Marking..." : "Mark all read"}
                  </Text>
                </Pressable>
              )}
            </>
          )}
        </View>

        {/* Tab picker */}
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {TABS.map(({ key, label }) => {
            const isActive = activeTab === key;
            const count = tabCounts[key];

            return (
              <Pressable
                key={key}
                onPress={() => {
                  setActiveTab(key);
                  if (isSelectMode) handleCancelSelect();
                }}
                style={{
                  borderRadius: 999,
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.xs,
                  backgroundColor: isActive
                    ? "rgba(22,193,255,0.2)"
                    : "rgba(255,255,255,0.07)",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isActive ? "#9fe6ff" : "#c5cad2",
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {label}
                </Text>
                {count > 0 && (
                  <View
                    style={{
                      backgroundColor: isActive
                        ? "rgba(22,193,255,0.3)"
                        : "rgba(255,255,255,0.1)",
                      borderRadius: 999,
                      minWidth: 18,
                      height: 18,
                      alignItems: "center",
                      justifyContent: "center",
                      paddingHorizontal: 4,
                    }}
                  >
                    <Text
                      style={{
                        fontSize: fontSize.xs - 2,
                        color: isActive ? "#9fe6ff" : "#8a9099",
                        fontWeight: "600",
                      }}
                    >
                      {count > 99 ? "99+" : count}
                    </Text>
                  </View>
                )}
              </Pressable>
            );
          })}
        </View>
      </View>

      <NotificationConnectBanner />

      <View style={{ flex: 1 }}>
        <NotificationsList
          notifications={notifications}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          error={error}
          emptyTitle={
            activeTab === "unread"
              ? "No unread notifications"
              : activeTab === "archived"
                ? "No archived notifications"
                : "No notifications yet"
          }
          emptyDescription={
            activeTab === "unread"
              ? "All caught up! You're up to date with everything."
              : activeTab === "archived"
                ? "Archived notifications will appear here."
                : "Notifications will appear here when you receive them."
          }
          onRefresh={() => {
            void refetch();
          }}
          onMarkAsRead={(notificationId: string) => {
            void markAsRead(notificationId);
          }}
          onArchive={
            activeTab !== "archived"
              ? (notificationId: string) => {
                  void archiveNotification(notificationId);
                }
              : undefined
          }
          onActionPress={(
            notification: InAppNotification,
            action: InAppNotificationAction,
          ) => {
            void executeNotificationAction(notification, action);
          }}
          isMarkingAsRead={isMarkingAsRead}
          isActionLoading={isActionLoading}
          isSelectMode={isSelectMode}
          selectedIds={selectedIds}
          onLongPress={handleLongPress}
          onSelectToggle={handleSelectToggle}
        />
      </View>

      {/* Bulk action bar */}
      {isSelectMode && selectedIds.size > 0 && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-around",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            paddingBottom: insets.bottom + spacing.sm,
            backgroundColor: "#1c1f26",
            borderTopWidth: 1,
            borderTopColor: "rgba(255,255,255,0.08)",
            gap: spacing.sm,
          }}
        >
          {activeTab !== "archived" && (
            <Pressable
              onPress={() => {
                void handleBulkMarkRead();
              }}
              style={{
                flex: 1,
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
                backgroundColor: "rgba(0,187,255,0.12)",
                borderRadius: 10,
                paddingVertical: spacing.sm + 2,
              }}
            >
              <AppIcon icon={Tick02Icon} size={16} color="#00bbff" />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#00bbff",
                  fontWeight: "500",
                }}
              >
                Mark Read
              </Text>
            </Pressable>
          )}

          {activeTab !== "archived" && (
            <Pressable
              onPress={() => {
                void handleBulkArchive();
              }}
              style={{
                flex: 1,
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
                backgroundColor: "rgba(251,191,36,0.1)",
                borderRadius: 10,
                paddingVertical: spacing.sm + 2,
              }}
            >
              <AppIcon icon={FolderIcon} size={16} color="#fbbf24" />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#fbbf24",
                  fontWeight: "500",
                }}
              >
                Archive
              </Text>
            </Pressable>
          )}

          <Pressable
            onPress={() => {
              void handleBulkDelete();
            }}
            style={{
              flex: 1,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              backgroundColor: "rgba(239,68,68,0.1)",
              borderRadius: 10,
              paddingVertical: spacing.sm + 2,
            }}
          >
            <AppIcon icon={Delete02Icon} size={16} color="#ef4444" />
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#ef4444",
                fontWeight: "500",
              }}
            >
              Delete
            </Text>
          </Pressable>
        </View>
      )}

      <NotificationPreferencesSheet ref={prefsSheetRef} />
    </View>
  );
}
