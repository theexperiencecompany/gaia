import { useState } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import {
  NotificationConnectBanner,
  NotificationsList,
  useInappNotifications,
  useNotificationActions,
} from "@/features/notifications";
import { useResponsive } from "@/lib/responsive";

type NotificationsTab = "unread" | "all";

export default function NotificationsScreen() {
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [activeTab, setActiveTab] = useState<NotificationsTab>("unread");
  const {
    unreadNotifications,
    allNotifications,
    isLoading,
    isRefreshing,
    error,
    refetch,
    markAsRead,
    markAllAsRead,
    isMarkingAsRead,
    isMarkingAllAsRead,
  } = useInappNotifications();
  const { executeNotificationAction, isActionLoading } =
    useNotificationActions();

  const notifications =
    activeTab === "unread" ? unreadNotifications : allNotifications;

  const handleMarkAllAsRead = async () => {
    await markAllAsRead(unreadNotifications.map((item) => item.id));
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
        </View>

        {/* Tab picker */}
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {(
            [
              ["unread", "Unread"],
              ["all", "All"],
            ] as const
          ).map(([tab, label]) => {
            const isActive = activeTab === tab;
            const count =
              tab === "unread"
                ? unreadNotifications.length
                : allNotifications.length;

            return (
              <Pressable
                key={tab}
                onPress={() => setActiveTab(tab)}
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
                      {count}
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
              : "No notifications yet"
          }
          emptyDescription={
            activeTab === "unread"
              ? "All caught up! You're up to date with everything."
              : "Notifications will appear here when you receive them."
          }
          onRefresh={() => {
            void refetch();
          }}
          onMarkAsRead={(notificationId) => {
            void markAsRead(notificationId);
          }}
          onActionPress={(notification, action) => {
            void executeNotificationAction(notification, action);
          }}
          isMarkingAsRead={isMarkingAsRead}
          isActionLoading={isActionLoading}
        />
      </View>
    </View>
  );
}
