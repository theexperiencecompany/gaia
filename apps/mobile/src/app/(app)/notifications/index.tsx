import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Button, Chip } from "heroui-native";
import { useState } from "react";
import { View } from "react-native";
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
            gap: spacing.sm,
          }}
        >
          <Button
            variant="tertiary"
            isIconOnly
            size="sm"
            onPress={() => router.back()}
            className="rounded-full bg-white/5"
          >
            <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Button>

          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              flex: 1,
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

          {unreadNotifications.length > 0 && (
            <Button
              size="sm"
              variant="tertiary"
              isDisabled={isMarkingAllAsRead}
              onPress={() => {
                void handleMarkAllAsRead();
              }}
              className="bg-primary/15 px-4"
            >
              <Button.Label className="text-primary text-xs">
                {isMarkingAllAsRead ? "Marking..." : "Mark all read"}
              </Button.Label>
            </Button>
          )}
        </View>

        {/* Tab picker */}
        <View
          style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}
        >
          {TABS.map(({ key, label }) => {
            const isActive = activeTab === key;
            const count =
              key === "unread"
                ? unreadNotifications.length
                : allNotifications.length;

            return (
              <Chip
                key={key}
                variant={isActive ? "primary" : "secondary"}
                color={isActive ? "accent" : "default"}
                onPress={() => setActiveTab(key)}
                className={isActive ? "" : "bg-white/10"}
              >
                <Chip.Label
                  className={
                    isActive ? "text-accent text-xs" : "text-[#c5cad2] text-xs"
                  }
                >
                  {count > 0
                    ? `${label} (${count > 99 ? "99+" : count})`
                    : label}
                </Chip.Label>
              </Chip>
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
