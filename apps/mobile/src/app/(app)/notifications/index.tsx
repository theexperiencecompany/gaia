import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Modal, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  Cancel01Icon,
  CheckmarkBadge01Icon,
  Delete02Icon,
  FolderIcon,
  MoreVerticalIcon,
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
import { BackButton } from "@/shared/components/ui/back-button";

type NotificationsTab = "unread" | "all";

const TABS: { key: NotificationsTab; label: string }[] = [
  { key: "unread", label: "Unread" },
  { key: "all", label: "All" },
];

export default function NotificationsScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<NotificationsTab>("unread");
  const [isSelectMode, setIsSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const prefsSheetRef = useRef<NotificationPreferencesSheetRef>(null);
  const snoozeSheetRef = useRef<NotificationSnoozeSheetRef>(null);

  const {
    unreadNotifications,
    allNotifications,
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
    activeTab === "unread" ? unreadNotifications : allNotifications;

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
  };

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      {/* Header — mirrors web NotificationsHeader.tsx structure:
          [back] [bell + "Notifications"] [Mark All as Read] [settings]
          Tabs row with count badge on Unread (web parity). */}
      <View
        style={{
          paddingTop: insets.top + 8,
          paddingHorizontal: 16,
          paddingBottom: 12,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.06)",
          gap: 12,
        }}
      >
        {/* Title row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
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
                  fontSize: 16,
                  fontWeight: "600",
                  color: "#e8ebef",
                  marginLeft: 8,
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
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                }}
              >
                <Text
                  style={{
                    color: "#00bbff",
                    fontSize: 12,
                    fontWeight: "500",
                  }}
                >
                  Select All
                </Text>
              </Pressable>
            </>
          ) : (
            <>
              <BackButton />

              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  marginLeft: 4,
                  flex: 1,
                }}
              >
                <AppIcon icon={Notification01Icon} size={20} color="#e8ebef" />
                <Text
                  style={{
                    fontSize: 17,
                    fontWeight: "600",
                    color: "#ffffff",
                  }}
                >
                  Notifications
                </Text>
              </View>

              <Pressable
                onPress={() => setIsMenuOpen(true)}
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 999,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "rgba(255,255,255,0.05)",
                }}
                hitSlop={6}
                accessibilityLabel="Notifications options"
              >
                <AppIcon icon={MoreVerticalIcon} size={18} color="#e4e4e7" />
              </Pressable>
            </>
          )}
        </View>

        {/* Tab picker — web NotificationsHeader uses <Tabs> from HeroUI
            (underlined). On mobile we render minimal underline-style tabs to
            keep visual parity with the web's quiet header treatment. */}
        <View
          style={{
            flexDirection: "row",
            gap: 24,
            paddingHorizontal: 4,
          }}
        >
          {TABS.map(({ key, label }) => {
            const isActive = activeTab === key;
            const count = tabCounts[key];
            const showBadge = key === "unread" && count > 0;

            return (
              <Pressable
                key={key}
                onPress={() => {
                  setActiveTab(key);
                  if (isSelectMode) handleCancelSelect();
                }}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  paddingVertical: 8,
                  borderBottomWidth: 2,
                  borderBottomColor: isActive ? "#00bbff" : "transparent",
                }}
              >
                <Text
                  // Web tab: text-sm; active uses primary, inactive zinc-500
                  style={{
                    fontSize: 14,
                    color: isActive ? "#ffffff" : "#71717a",
                    fontWeight: isActive ? "600" : "500",
                  }}
                >
                  {label}
                </Text>
                {showBadge && (
                  // Web Unread badge:
                  //   ml-0.5 flex h-5 min-w-5 rounded-full bg-primary/10
                  //   px-1.5 text-xs font-semibold text-primary
                  <View
                    style={{
                      minWidth: 20,
                      height: 20,
                      borderRadius: 10,
                      paddingHorizontal: 6,
                      backgroundColor: "rgba(0,187,255,0.10)",
                      alignItems: "center",
                      justifyContent: "center",
                      marginLeft: 2,
                    }}
                  >
                    <Text
                      style={{
                        fontSize: 12,
                        fontWeight: "600",
                        color: "#00bbff",
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
            activeTab === "unread" ? "You're all caught up" : "Nothing here yet"
          }
          emptyDescription={
            activeTab === "unread"
              ? "Take a breath."
              : "GAIA will surface things that need your attention."
          }
          emptyActionLabel="Notification preferences"
          onEmptyAction={() => prefsSheetRef.current?.open()}
          onRefresh={() => {
            void refetch();
          }}
          onMarkAsRead={(notificationId: string) => {
            void markAsRead(notificationId);
          }}
          onArchive={(notificationId: string) => {
            void archiveNotification(notificationId);
          }}
          onSnooze={handleSnooze}
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

      <Modal
        visible={isMenuOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setIsMenuOpen(false)}
      >
        <Pressable
          onPress={() => setIsMenuOpen(false)}
          style={{
            flex: 1,
            backgroundColor: "rgba(0,0,0,0.4)",
            justifyContent: "flex-start",
          }}
        >
          <View
            style={{
              marginTop: insets.top + 56,
              marginRight: 16,
              alignSelf: "flex-end",
              minWidth: 220,
              backgroundColor: "#1c1f26",
              borderRadius: 14,
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.06)",
              overflow: "hidden",
            }}
          >
            <Pressable
              disabled={isMarkingAllAsRead || unreadNotifications.length === 0}
              onPress={() => {
                setIsMenuOpen(false);
                void handleMarkAllAsRead();
              }}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 10,
                paddingHorizontal: 14,
                paddingVertical: 12,
                opacity:
                  unreadNotifications.length === 0 || isMarkingAllAsRead
                    ? 0.4
                    : 1,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.04)"
                  : "transparent",
              })}
            >
              <AppIcon icon={CheckmarkBadge01Icon} size={16} color="#e4e4e7" />
              <Text style={{ color: "#e4e4e7", fontSize: 14 }}>
                Mark all as read
              </Text>
            </Pressable>
            <View
              style={{
                height: 1,
                backgroundColor: "rgba(255,255,255,0.06)",
              }}
            />
            <Pressable
              onPress={() => {
                setIsMenuOpen(false);
                prefsSheetRef.current?.open();
              }}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 10,
                paddingHorizontal: 14,
                paddingVertical: 12,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.04)"
                  : "transparent",
              })}
            >
              <AppIcon icon={Settings01Icon} size={16} color="#e4e4e7" />
              <Text style={{ color: "#e4e4e7", fontSize: 14 }}>
                Notification preferences
              </Text>
            </Pressable>
            <View
              style={{
                height: 1,
                backgroundColor: "rgba(255,255,255,0.06)",
              }}
            />
            <Pressable
              onPress={() => {
                setIsMenuOpen(false);
                // "Filter" cycles to the next tab — quick keyboard-free filter.
                const nextIdx =
                  (TABS.findIndex((t) => t.key === activeTab) + 1) %
                  TABS.length;
                const next = TABS[nextIdx];
                if (next) setActiveTab(next.key);
              }}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 10,
                paddingHorizontal: 14,
                paddingVertical: 12,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.04)"
                  : "transparent",
              })}
            >
              <AppIcon icon={FolderIcon} size={16} color="#e4e4e7" />
              <Text style={{ color: "#e4e4e7", fontSize: 14 }}>Filter</Text>
            </Pressable>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}
