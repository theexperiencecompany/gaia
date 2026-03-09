import { FlatList, RefreshControl, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type {
  InAppNotification,
  InAppNotificationAction,
} from "../types/inapp-notification-types";
import { NotificationCard } from "./notification-card";

interface NotificationsListProps {
  notifications: InAppNotification[];
  isLoading: boolean;
  isRefreshing?: boolean;
  error?: string | null;
  emptyTitle: string;
  emptyDescription: string;
  onRefresh: () => void;
  onMarkAsRead: (notificationId: string) => void;
  onActionPress: (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ) => void;
  isMarkingAsRead?: boolean;
  isActionLoading?: (notificationId: string, actionId: string) => boolean;
}

export function NotificationsList({
  notifications,
  isLoading,
  isRefreshing = false,
  error,
  emptyTitle,
  emptyDescription,
  onRefresh,
  onMarkAsRead,
  onActionPress,
  isMarkingAsRead = false,
  isActionLoading,
}: NotificationsListProps) {
  const { spacing, fontSize } = useResponsive();

  if (isLoading) {
    return (
      <View style={{ padding: spacing.lg }}>
        <Text style={{ color: "#8a9099", fontSize: fontSize.sm }}>
          Loading notifications...
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={{ padding: spacing.lg }}>
        <Text style={{ color: "#f87171", fontSize: fontSize.sm }}>{error}</Text>
      </View>
    );
  }

  if (notifications.length === 0) {
    return (
      <View style={{ padding: spacing.lg, gap: spacing.sm }}>
        <Text style={{ color: "#e8ebef", fontSize: fontSize.sm }}>
          {emptyTitle}
        </Text>
        <Text style={{ color: "#8a9099", fontSize: fontSize.xs }}>
          {emptyDescription}
        </Text>
      </View>
    );
  }

  return (
    <FlatList
      data={notifications}
      keyExtractor={(item) => item.id}
      contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={onRefresh}
          tintColor="#16c1ff"
        />
      }
      renderItem={({ item }) => (
        <NotificationCard
          notification={item}
          onMarkAsRead={onMarkAsRead}
          onActionPress={onActionPress}
          isMarkingAsRead={isMarkingAsRead}
          isActionLoading={(actionId) => !!isActionLoading?.(item.id, actionId)}
        />
      )}
    />
  );
}
