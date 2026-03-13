import { useMemo } from "react";
import { FlatList, RefreshControl, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, Notification01Icon } from "@/components/icons";
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
  onDismiss?: (notificationId: string) => void;
  onArchive?: (notificationId: string) => void;
  onSnooze?: (notificationId: string) => void;
  onActionPress: (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ) => void;
  isMarkingAsRead?: boolean;
  isActionLoading?: (notificationId: string, actionId: string) => boolean;
  isSelectMode?: boolean;
  selectedIds?: Set<string>;
  onLongPress?: (notificationId: string) => void;
  onSelectToggle?: (notificationId: string) => void;
}

function getTimeGroup(dateString: string): string {
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return "Earlier";

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const notifDate = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );

  if (notifDate.getTime() >= today.getTime()) return "Today";
  if (notifDate.getTime() >= yesterday.getTime()) return "Yesterday";
  return "Earlier";
}

type GroupedSection =
  | { type: "header"; title: string }
  | { type: "notification"; notification: InAppNotification };

interface SkeletonItemProps {
  spacing: { md: number; sm: number };
  moderateScale: (size: number, factor?: number) => number;
}

function SkeletonItem({ spacing, moderateScale }: SkeletonItemProps) {
  return (
    <View
      style={{
        borderRadius: moderateScale(16, 0.5),
        backgroundColor: "#171920",
        padding: spacing.md,
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.sm,
        marginBottom: spacing.sm,
      }}
    >
      <View
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          backgroundColor: "rgba(255,255,255,0.06)",
        }}
      />
      <View style={{ flex: 1, gap: 8 }}>
        <View
          style={{
            height: 14,
            borderRadius: 7,
            backgroundColor: "rgba(255,255,255,0.07)",
            width: "70%",
          }}
        />
        <View
          style={{
            height: 11,
            borderRadius: 6,
            backgroundColor: "rgba(255,255,255,0.04)",
            width: "90%",
          }}
        />
        <View
          style={{
            height: 11,
            borderRadius: 6,
            backgroundColor: "rgba(255,255,255,0.04)",
            width: "55%",
          }}
        />
        <View
          style={{
            height: 10,
            borderRadius: 5,
            backgroundColor: "rgba(255,255,255,0.03)",
            width: "25%",
            alignSelf: "flex-end",
          }}
        />
      </View>
    </View>
  );
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
  onDismiss,
  onArchive,
  onSnooze,
  onActionPress,
  isMarkingAsRead = false,
  isActionLoading,
  isSelectMode = false,
  selectedIds,
  onLongPress,
  onSelectToggle,
}: NotificationsListProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const insets = useSafeAreaInsets();

  const sections = useMemo(() => {
    const groups: Record<string, InAppNotification[]> = {};
    for (const n of notifications) {
      const group = getTimeGroup(n.created_at);
      if (!groups[group]) groups[group] = [];
      groups[group].push(n);
    }

    const order = ["Today", "Yesterday", "Earlier"];
    const result: GroupedSection[] = [];
    for (const key of order) {
      if (groups[key] && groups[key].length > 0) {
        result.push({ type: "header", title: key });
        for (const n of groups[key]) {
          result.push({ type: "notification", notification: n });
        }
      }
    }
    return result;
  }, [notifications]);

  if (isLoading) {
    return (
      <View style={{ flex: 1, padding: spacing.md }}>
        {[0, 1, 2, 3].map((i) => (
          <SkeletonItem
            key={i}
            spacing={spacing}
            moderateScale={moderateScale}
          />
        ))}
      </View>
    );
  }

  if (error) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          padding: spacing.lg,
        }}
      >
        <Text
          style={{
            color: "#f87171",
            fontSize: fontSize.sm,
            textAlign: "center",
          }}
        >
          {error}
        </Text>
      </View>
    );
  }

  if (notifications.length === 0) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          padding: spacing.lg,
          gap: spacing.md,
        }}
      >
        <View
          style={{
            width: 64,
            height: 64,
            borderRadius: 32,
            backgroundColor: "rgba(255,255,255,0.04)",
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.07)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <AppIcon icon={Notification01Icon} size={28} color="#48484a" />
        </View>
        <View style={{ alignItems: "center", gap: 4 }}>
          <Text
            style={{
              color: "#e8ebef",
              fontSize: fontSize.base,
              fontWeight: "600",
            }}
          >
            {emptyTitle}
          </Text>
          <Text
            style={{
              color: "#8e8e93",
              fontSize: fontSize.sm,
              textAlign: "center",
            }}
          >
            {emptyDescription}
          </Text>
        </View>
      </View>
    );
  }

  return (
    <FlatList
      data={sections}
      keyExtractor={(item, index) =>
        item.type === "header" ? `header-${item.title}` : `notif-${index}`
      }
      contentContainerStyle={{
        padding: spacing.md,
        paddingBottom: insets.bottom + spacing.lg,
      }}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={onRefresh}
          tintColor="#00bbff"
        />
      }
      renderItem={({ item }) => {
        if (item.type === "header") {
          return (
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "600",
                letterSpacing: 0.8,
                textTransform: "uppercase",
                color: "#8e8e93",
                paddingVertical: spacing.sm,
                paddingHorizontal: 2,
                marginTop: spacing.sm,
              }}
            >
              {item.title}
            </Text>
          );
        }

        return (
          <View style={{ marginBottom: spacing.sm }}>
            <NotificationCard
              notification={item.notification}
              onMarkAsRead={onMarkAsRead}
              onDismiss={onDismiss}
              onArchive={onArchive}
              onSnooze={onSnooze}
              onActionPress={onActionPress}
              isMarkingAsRead={isMarkingAsRead}
              isActionLoading={(actionId) =>
                !!isActionLoading?.(item.notification.id, actionId)
              }
              isSelectMode={isSelectMode}
              isSelected={selectedIds?.has(item.notification.id) ?? false}
              onLongPress={onLongPress}
              onSelectToggle={onSelectToggle}
            />
          </View>
        );
      }}
    />
  );
}
