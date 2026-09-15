import { parseRelativeDateLabel } from "@gaia/shared/utils";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  CheckmarkBadge01Icon,
  CheckmarkCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { InAppNotification } from "../types/inapp-notification-types";

interface NotificationSelectionCheckboxProps {
  isSelected: boolean;
}

/** Circular multi-select indicator shown at the card's leading edge. */
function NotificationSelectionCheckbox({
  isSelected,
}: NotificationSelectionCheckboxProps) {
  return (
    <View
      style={{
        width: 22,
        height: 22,
        borderRadius: 11,
        borderWidth: 2,
        borderColor: isSelected ? "#00bbff" : "#48484a",
        backgroundColor: isSelected ? "rgba(0,187,255,0.20)" : "transparent",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        marginTop: 2,
      }}
    >
      {isSelected && (
        <AppIcon icon={CheckmarkCircle02Icon} size={14} color="#00bbff" />
      )}
    </View>
  );
}

interface NotificationCardHeaderProps {
  notification: InAppNotification;
  isUnread: boolean;
  isSelectMode: boolean;
  isSelected: boolean;
  isMarkingAsRead: boolean;
  onMarkAsRead: () => void;
}

/**
 * Top row of the card: selection checkbox (select mode), title + body, and
 * the trailing meta column (timestamp + mark-as-read when unread).
 */
export function NotificationCardHeader({
  notification,
  isUnread,
  isSelectMode,
  isSelected,
  isMarkingAsRead,
  onMarkAsRead,
}: NotificationCardHeaderProps) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 12,
      }}
    >
      {isSelectMode && (
        <NotificationSelectionCheckbox isSelected={isSelected} />
      )}

      {/* Main content: title + body. Mirrors web's `space-y-1` (4px). */}
      <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
        {/* Title row with unread dot — web: gap-2 (8px) */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
          }}
        >
          <Text
            // Web: text-[15px] leading-tight font-semibold
            // unread → text-white, read → text-zinc-500
            style={{
              flexShrink: 1,
              fontSize: 15,
              lineHeight: 18,
              fontWeight: "600",
              color: isUnread ? "#ffffff" : "#71717a",
            }}
            numberOfLines={2}
          >
            {notification.content.title}
          </Text>
          {isUnread && (
            <View
              // Web: h-1.5 w-1.5 rounded-full bg-primary (6×6)
              style={{
                width: 6,
                height: 6,
                borderRadius: 3,
                backgroundColor: "#00bbff",
                flexShrink: 0,
              }}
            />
          )}
        </View>

        {/* Body — web: text-[13px], unread→zinc-400, read→zinc-600
            Default line-height ≈ 1.5×13 = 19.5. */}
        {!!notification.content.body && (
          <Text
            numberOfLines={3}
            style={{
              fontSize: 13,
              lineHeight: 20,
              color: isUnread ? "#a1a1aa" : "#52525b",
            }}
          >
            {notification.content.body}
          </Text>
        )}
      </View>

      {/* Top-right meta column: timestamp + (when unread) mark-as-read.
          Linear-style — time anchors the corner, not buried in a footer. */}
      {!isSelectMode && (
        <View
          style={{
            flexShrink: 0,
            alignItems: "flex-end",
            gap: 6,
            marginTop: 1,
          }}
        >
          <Text
            style={{
              fontSize: 11,
              color: "#52525b",
            }}
          >
            {parseRelativeDateLabel(notification.created_at)}
          </Text>
          {isUnread && (
            <Pressable
              disabled={isMarkingAsRead}
              onPress={onMarkAsRead}
              hitSlop={10}
              style={{
                opacity: isMarkingAsRead ? 0.4 : 1,
                width: 24,
                height: 24,
                borderRadius: 12,
                alignItems: "center",
                justifyContent: "center",
              }}
              accessibilityLabel="Mark as read"
            >
              <AppIcon icon={CheckmarkBadge01Icon} size={16} color="#71717a" />
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
}
