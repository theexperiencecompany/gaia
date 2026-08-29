import { spacingTokens } from "@gaia/shared/design";
import { type DateGroup, groupAndSortByDateGroup } from "@gaia/shared/utils";
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

/**
 * Notifications list — headers unified to shared `dateGroups`.
 *
 * Shared contract (libs/shared/ts/src/utils/dateGroups.ts):
 *   getDateGroup(value, now) → "Today" | "Yesterday" | "Previous 7 days" | "Previous 30 days" | "All time"
 *   DATE_GROUPS canonical order, compareDateGroup, groupAndSortByDateGroup
 *   groupAndSortByDateGroup(items, getDate, now) → sorted [DateGroup, T[]][] newest-first within each bucket
 *
 * Mobile previously used local getTimeGroup → Today/Yesterday/This Week/Earlier.
 * Web uses shared 5-bucket taxonomy. This file now imports the same shared taxonomy so grouping + labels are byte-for-byte identical.
 *
 * Spacing: horizontal padding uses shared gutter token (16px) so it stays 1:1 with web px-6 (24px) minus the tighter mobile lane.
 * Header typography matches web: text-xs font-semibold tracking-wider text-zinc-500 uppercase (12/600/1px/#71717a).
 *
 * @see libs/shared/ts/src/utils/dateGroups.ts
 * @see apps/web/src/features/notification/components/NotificationsList.tsx
 */

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

// Keep the sparse threshold semantics (drop "All time" header on tiny lists)
// but map it to the shared bucket name.
const SPARSE_LIST_THRESHOLD = 10;

type GroupedSection =
  | { type: "header"; title: DateGroup }
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
    // Single shared grouping — replaces local getTimeGroup/TIME_GROUP_ORDER.
    // groupAndSortByDateGroup sorts groups by DATE_GROUPS order and items newest-first.
    const sorted = groupAndSortByDateGroup(notifications, (n) => n.created_at);

    const isSparse = notifications.length < SPARSE_LIST_THRESHOLD;
    const result: GroupedSection[] = [];
    for (const [groupLabel, bucket] of sorted) {
      if (bucket.length === 0) continue;
      // Preserve sparse-list ceremony: hide "All time" header when the pile is tiny.
      const skipHeader = groupLabel === "All time" && isSparse;
      if (!skipHeader) {
        result.push({ type: "header", title: groupLabel });
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

  // Shared spacing token for horizontal lane — gutter 16px (shared) matches web px-6 minus mobile tightness choice.
  const horizontalPadding = Number(spacingTokens.gutter.replace("px", "")); // 16

  return (
    <FlatList
      data={sections}
      keyExtractor={(item, index) =>
        item.type === "header" ? `header-${item.title}` : `notif-${index}`
      }
      contentContainerStyle={{
        paddingHorizontal: horizontalPadding,
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
          return (
            <Text
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

export type { DateGroup } from "@gaia/shared/utils";
// Re-export shared dateGroups for callers that previously imported from this file.
// Prefer importing directly from "@gaia/shared/utils" in new code.
export { DATE_GROUPS, getDateGroup } from "@gaia/shared/utils";
