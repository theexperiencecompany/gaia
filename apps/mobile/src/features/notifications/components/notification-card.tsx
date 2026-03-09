import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type {
  InAppNotification,
  InAppNotificationAction,
} from "../types/inapp-notification-types";

interface NotificationCardProps {
  notification: InAppNotification;
  onMarkAsRead: (notificationId: string) => void;
  onActionPress: (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ) => void;
  isMarkingAsRead?: boolean;
  isActionLoading?: (actionId: string) => boolean;
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Now";
  }

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function NotificationCard({
  notification,
  onMarkAsRead,
  onActionPress,
  isMarkingAsRead = false,
  isActionLoading,
}: NotificationCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const isUnread = notification.status !== "read";

  return (
    <View
      style={{
        borderRadius: moderateScale(16, 0.5),
        borderWidth: 1,
        borderColor: isUnread
          ? "rgba(22,193,255,0.35)"
          : "rgba(255,255,255,0.08)",
        backgroundColor: "#14171c",
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <View style={{ flex: 1, gap: spacing.xs }}>
          <Text style={{ fontSize: fontSize.sm, color: "#e8ebef" }}>
            {notification.content.title}
          </Text>
          <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
            {formatDate(notification.created_at)}
          </Text>
        </View>
        {isUnread && (
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              backgroundColor: "#16c1ff",
            }}
          />
        )}
      </View>

      <Text style={{ fontSize: fontSize.sm, color: "#c5cad2" }}>
        {notification.content.body}
      </Text>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        {notification.content.actions?.map((action) => {
          const actionLoading = isActionLoading?.(action.id) ?? false;

          return (
            <Pressable
              key={action.id}
              disabled={actionLoading || action.disabled}
              onPress={() => onActionPress(notification, action)}
              style={{
                borderRadius: 999,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.xs,
                backgroundColor: "rgba(255,255,255,0.09)",
                opacity: actionLoading || action.disabled ? 0.5 : 1,
              }}
            >
              <Text style={{ fontSize: fontSize.xs, color: "#e8ebef" }}>
                {actionLoading ? "Working..." : action.label}
              </Text>
            </Pressable>
          );
        })}

        {isUnread && (
          <Pressable
            disabled={isMarkingAsRead}
            onPress={() => onMarkAsRead(notification.id)}
            style={{
              borderRadius: 999,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.xs,
              backgroundColor: "rgba(22,193,255,0.18)",
              opacity: isMarkingAsRead ? 0.6 : 1,
            }}
          >
            <Text style={{ fontSize: fontSize.xs, color: "#9fe6ff" }}>
              {isMarkingAsRead ? "Saving..." : "Mark read"}
            </Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}
