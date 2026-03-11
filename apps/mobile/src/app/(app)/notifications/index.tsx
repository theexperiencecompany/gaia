import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  Notification01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  NotificationConnectBanner,
  NotificationsList,
  useInappNotifications,
  useNotificationActions,
  useRealtimeNotifications,
} from "@/features/notifications";
import { useResponsive } from "@/lib/responsive";

type NotificationsTab = "unread" | "all";

export default function NotificationsScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
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

  const TABS: { key: NotificationsTab; label: string }[] = [
    { key: "unread", label: "Unread" },
    { key: "all", label: "All" },
  ];

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
          }}
        >
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
            <AppIcon
              icon={Notification01Icon}
              size={18}
              color="#8e8e93"
            />
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
        </View>

        {/* Tab picker */}
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {TABS.map(({ key, label }) => {
            const isActive = activeTab === key;
            const count =
              key === "unread"
                ? unreadNotifications.length
                : allNotifications.length;

            return (
              <Pressable
                key={key}
                onPress={() => setActiveTab(key)}
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
                        ? "rgba(0,187,255,0.28)"
                        : "rgba(255,255,255,0.09)",
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
                        color: isActive ? "#9fe6ff" : "#8e8e93",
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
