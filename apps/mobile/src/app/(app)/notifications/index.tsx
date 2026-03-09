import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { ArrowLeft01Icon, HugeiconsIcon } from "@/components/icons";
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
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
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
      <View
        style={{
          paddingTop: spacing.xl * 2,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          gap: spacing.md,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center" }}>
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
            <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>

          <Text style={{ marginLeft: spacing.md, fontSize: fontSize.base }}>
            Notifications
          </Text>

          <View style={{ flex: 1 }} />

          {unreadNotifications.length > 0 && (
            <Pressable
              disabled={isMarkingAllAsRead}
              onPress={() => {
                void handleMarkAllAsRead();
              }}
              style={{ opacity: isMarkingAllAsRead ? 0.6 : 1 }}
            >
              <Text style={{ color: "#9fe6ff", fontSize: fontSize.xs }}>
                {isMarkingAllAsRead ? "Marking..." : "Mark all read"}
              </Text>
            </Pressable>
          )}
        </View>

        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {(
            [
              ["unread", "Unread"],
              ["all", "All"],
            ] as const
          ).map(([tab, label]) => {
            const isActive = activeTab === tab;

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
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isActive ? "#9fe6ff" : "#c5cad2",
                  }}
                >
                  {label}
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
            activeTab === "unread" ? "All caught up" : "No notifications yet"
          }
          emptyDescription={
            activeTab === "unread"
              ? "You have no unread notifications right now."
              : "Incoming updates and actions will appear here."
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
