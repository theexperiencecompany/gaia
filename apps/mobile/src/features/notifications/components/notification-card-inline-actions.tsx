import { Pressable, View } from "react-native";
import type { AnyIcon } from "@/components/icons";
import {
  AlertCircleIcon,
  AppIcon,
  CheckmarkCircle02Icon,
  LinkSquare02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type {
  InAppNotification,
  InAppNotificationAction,
} from "../types/inapp-notification-types";

interface ActionTone {
  bg: string;
  text: string;
}

// Web tones (apps/web .../EnhancedNotificationCard.tsx):
//   primary  → bg-primary/10 text-primary
//   danger   → bg-red-500/10 text-red-500
//   default  → bg-zinc-800/50 text-zinc-400
function getActionTone(style?: string): ActionTone {
  switch (style) {
    case "primary":
      return { bg: "rgba(0,187,255,0.10)", text: "#00bbff" };
    case "danger":
      return { bg: "rgba(239,68,68,0.10)", text: "#ef4444" };
    default:
      return { bg: "rgba(39,39,42,0.50)", text: "#a1a1aa" };
  }
}

function getActionIcon(type: InAppNotificationAction["type"]): AnyIcon | null {
  switch (type) {
    case "redirect":
      return LinkSquare02Icon;
    case "api_call":
      return CheckmarkCircle02Icon;
    case "modal":
      return AlertCircleIcon;
    default:
      return null;
  }
}

interface NotificationActionChipProps {
  action: InAppNotificationAction;
  loading: boolean;
  onPress: () => void;
}

/** One tappable action pill; disabled while loading, disabled, or executed. */
function NotificationActionChip({
  action,
  loading,
  onPress,
}: NotificationActionChipProps) {
  const executed = action.executed ?? false;
  const showLoading = loading && action.type !== "modal";
  const tone = getActionTone(action.style);
  const trailingIcon = executed
    ? CheckmarkCircle02Icon
    : getActionIcon(action.type);
  return (
    <Pressable
      disabled={loading || action.disabled || executed}
      onPress={onPress}
      style={{
        borderRadius: 8,
        paddingHorizontal: 14,
        paddingVertical: 9,
        minHeight: 32,
        backgroundColor: tone.bg,
        opacity: loading || action.disabled || executed ? 0.6 : 1,
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
      }}
    >
      {showLoading ? (
        <Text
          style={{
            fontSize: 12,
            color: tone.text,
            fontWeight: "400",
          }}
        >
          ...
        </Text>
      ) : (
        <>
          <Text
            style={{
              fontSize: 12,
              color: tone.text,
              fontWeight: "400",
            }}
          >
            {action.label}
          </Text>
          {trailingIcon && (
            <AppIcon icon={trailingIcon} size={12} color={tone.text} />
          )}
        </>
      )}
    </Pressable>
  );
}

interface NotificationInlineActionsProps {
  notification: InAppNotification;
  actions: InAppNotificationAction[];
  isUnread: boolean;
  isActionLoading?: (actionId: string) => boolean;
  onActionPress: (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ) => void;
}

/** Wrapping row of action chips beneath the card body. */
export function NotificationInlineActions({
  notification,
  actions,
  isUnread,
  isActionLoading,
  onActionPress,
}: NotificationInlineActionsProps) {
  return (
    <View
      style={{
        marginTop: 12,
        flexDirection: "row",
        flexWrap: "wrap",
        gap: 8,
        opacity: isUnread ? 1 : 0.6,
      }}
    >
      {actions.map((action) => (
        <NotificationActionChip
          key={action.id}
          action={action}
          loading={isActionLoading?.(action.id) ?? false}
          onPress={() => onActionPress(notification, action)}
        />
      ))}
    </View>
  );
}
