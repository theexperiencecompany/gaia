import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  Cancel01Icon,
  Delete02Icon,
  FolderIcon,
  Notification01Icon,
  Settings01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { NotificationPreferencesSheetRef } from "@/features/notifications/components/NotificationPreferencesSheet";
import { NotificationPreferencesSheet } from "@/features/notifications/components/NotificationPreferencesSheet";
import type { NotificationSnoozeSheetRef } from "@/features/notifications/components/NotificationSnoozeSheet";
import { NotificationSnoozeSheet } from "@/features/notifications/components/NotificationSnoozeSheet";
import { NotificationConnectBanner } from "@/features/notifications/components/notification-connect-banner";
import { NotificationsList } from "@/features/notifications/components/notifications-list";
import { useInappNotifications } from "@/features/notifications/hooks/use-inapp-notifications";
import { useNotificationActions } from "@/features/notifications/hooks/use-notification-actions";
import { useRealtimeNotifications } from "@/features/notifications/hooks/use-realtime-notifications";
import type {
  InAppNotification,
  InAppNotificationAction,
} from "@/features/notifications/types/inapp-notification-types";
import { getNotificationRoute } from "@/features/notifications/utils/notification-routes";
import { useResponsive } from "@/lib/responsive";

type NotificationsTab = "unread" | "all" | "archived";

const TABS: { key: NotificationsTab; label: string }[] = [
  { key: "unread", label: "Unread" },
  { key: "all", label: "All" },
  { key: "archived", label: "Archived" },
];

export default function NotificationsScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<NotificationsTab>("unread");
  const [isSelectMode, setIsSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const prefsSheetRef = useRef<NotificationPreferencesSheetRef>(null);
  const snoozeSheetRef = useRef<NotificationSnoozeSheetRef>(null);

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

  // Real-time notifications via WebSocket — invalidate queries on new delivery
  useRealtimeNotifications({
    showLocalNotification: false,
    onNotificationReceived: () => {
      void queryClient.invalidateQueries({
        queryKey: ["inapp-notifications"],
      });
    },
    onNotificationRead: () => {
      void queryClient.invalidateQueries({
        queryKey: ["inapp-notifications"],
      });
    },
  });

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

  const handleSnooze = (notificationId: string) => {
    snoozeSheetRef.current?.open(notificationId);
  };

  const handleActionPress = (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ) => {
    void executeNotificationAction(notification, action);

    // For non-redirect actions, navigate to the inferred route if available.
    if (action.type !== "redirect") {
      const route = getNotificationRoute(notification);
      if (route) {
        router.push(route as never);
      }
    }
  };

  const tabCounts: Record<NotificationsTab, number> = {
    unread: unreadNotifications.length,
    all: allNotifications.length,
    archived: archivedNotifications.length,
  };

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.07)",
          gap: spacing.md,
        }}
      >
        {/* Title row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          {isSelectMode ? (
            <>
              <Pressable
                onPress={handleCancelSelect}
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 999,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "rgba(255,255,255,0.05)",
                }}
              >
                <AppIcon icon={Cancel01Icon} size={18} color="#fff" />
              </Pressable>

              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#e8ebef",
                  marginLeft: spacing.sm + 4,
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
                    color: "#00bbff",
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
              <Pressable
                onPress={() => router.back()}
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 999,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "rgba(255,255,255,0.05)",
                }}
              >
                <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
              </Pressable>

              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  marginLeft: spacing.sm + 4,
                }}
              >
                <AppIcon icon={Notification01Icon} size={18} color="#8e8e93" />
                <Text
                  style={{
                    fontSize: fontSize.base,
                    fontWeight: "600",
                    color: "#e8ebef",
                  }}
                >
                  Notifications
                </Text>
              </View>

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
                    backgroundColor: "rgba(0,187,255,0.1)",
                    borderRadius: 8,
                    paddingHorizontal: spacing.md,
                    paddingVertical: 6,
                  }}
                >
                  <Text
                    style={{
                      color: "#00bbff",
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
        <View
          style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}
        >
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
                    ? "rgba(0,187,255,0.18)"
                    : "rgba(255,255,255,0.06)",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isActive ? "#00bbff" : "#c5cad2",
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {count > 0
                    ? `${label} (${count > 99 ? "99+" : count})`
                    : label}
                </Text>
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
          onSnooze={activeTab !== "archived" ? handleSnooze : undefined}
          onActionPress={handleActionPress}
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
      <NotificationSnoozeSheet ref={snoozeSheetRef} />
    </View>
  );
}
