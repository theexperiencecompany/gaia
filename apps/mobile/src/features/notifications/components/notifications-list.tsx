import { useMemo } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
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
  onEmptyAction?: () => void;
  emptyActionLabel?: string;
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

type TimeGroupKey = "today" | "yesterday" | "thisWeek" | "earlier";

const TIME_GROUP_LABELS: Record<TimeGroupKey, string> = {
  today: "Today",
  yesterday: "Yesterday",
  thisWeek: "This Week",
  earlier: "Earlier",
};

const TIME_GROUP_ORDER: TimeGroupKey[] = [
  "today",
  "yesterday",
  "thisWeek",
  "earlier",
];

const SPARSE_LIST_THRESHOLD = 10;

function getTimeGroup(dateString: string): TimeGroupKey {
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return "earlier";

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const sevenDaysAgo = new Date(today);
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

  const notifDate = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );

  if (notifDate.getTime() >= today.getTime()) return "today";
  if (notifDate.getTime() >= yesterday.getTime()) return "yesterday";
  if (notifDate.getTime() >= sevenDaysAgo.getTime()) return "thisWeek";
  return "earlier";
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
  onEmptyAction,
  emptyActionLabel,
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
    const groups: Record<TimeGroupKey, InAppNotification[]> = {
      today: [],
      yesterday: [],
      thisWeek: [],
      earlier: [],
    };
    for (const n of notifications) {
      groups[getTimeGroup(n.created_at)].push(n);
    }

    // Drop the "Earlier" header when the list is sparse (<10 total) so we
    // don't add ceremony around a tiny pile.
    const isSparse = notifications.length < SPARSE_LIST_THRESHOLD;
    const result: GroupedSection[] = [];
    for (const key of TIME_GROUP_ORDER) {
      const bucket = groups[key];
      if (bucket.length === 0) continue;
      const skipHeader = key === "earlier" && isSparse;
      if (!skipHeader) {
        result.push({ type: "header", title: TIME_GROUP_LABELS[key] });
      }
      for (const n of bucket) {
        result.push({ type: "notification", notification: n });
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
    // Web parity (NotificationsList.tsx empty state):
    //   16×16 zinc-900/50 ring zinc-800 circle, NotificationIcon
    //   title: text-base font-semibold text-white
    //   desc:  text-sm text-zinc-500
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          gap: 16,
        }}
      >
        <View
          style={{
            width: 64,
            height: 64,
            borderRadius: 32,
            backgroundColor: "rgba(24,24,27,0.5)",
            borderWidth: 1,
            borderColor: "#27272a",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <AppIcon icon={Notification01Icon} size={28} color="#52525b" />
        </View>
        <View style={{ alignItems: "center", gap: 4 }}>
          <Text
            style={{
              color: "#ffffff",
              fontSize: 16,
              fontWeight: "600",
            }}
          >
            {emptyTitle}
          </Text>
          <Text
            style={{
              color: "#71717a",
              fontSize: 14,
              textAlign: "center",
            }}
          >
            {emptyDescription}
          </Text>
        </View>
        {onEmptyAction ? (
          <Pressable
            onPress={onEmptyAction}
            style={{
              marginTop: 8,
              borderRadius: 12,
              borderWidth: 1,
              borderColor: "#3f3f46",
              paddingVertical: 10,
              paddingHorizontal: 18,
            }}
          >
            <Text
              style={{
                color: "#e4e4e7",
                fontSize: 13,
                fontWeight: "500",
              }}
            >
              {emptyActionLabel ?? "Notification preferences"}
            </Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  return (
    <FlatList
      data={sections}
      keyExtractor={(item, index) =>
        item.type === "header" ? `header-${item.title}` : `notif-${index}`
      }
      // Web container uses `px-6 py-6` (24px) — but on mobile keep tighter
      // horizontal padding (16) so cards don't feel cramped at 1080w.
      contentContainerStyle={{
        paddingHorizontal: 16,
        paddingTop: 12,
        paddingBottom: insets.bottom + 24,
      }}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={onRefresh}
          tintColor="#00bbff"
        />
      }
      renderItem={({ item, index }) => {
        if (item.type === "header") {
          // Web: text-xs font-semibold tracking-wider text-zinc-500 uppercase
          // Group separation: `space-y-8` between groups, `space-y-3` inside.
          return (
            <Text
              // Web: text-xs font-semibold tracking-wider text-zinc-500 uppercase
              //   text-xs = 12 (web). Section spacing is space-y-8 between groups
              //   (32px gap) and space-y-3 (12px) before first card inside a group.
              style={{
                fontSize: 12,
                fontWeight: "600",
                letterSpacing: 1,
                textTransform: "uppercase",
                color: "#71717a",
                marginTop: index === 0 ? 8 : 32,
                marginBottom: 12,
                paddingHorizontal: 2,
              }}
            >
              {item.title}
            </Text>
          );
        }

        return (
          // Web: cards inside a group are spaced `space-y-2.5` (10px).
          <View style={{ marginBottom: 10 }}>
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
