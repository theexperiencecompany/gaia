import { Pressable, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import { useNotificationCardGestures } from "../hooks/use-notification-card-gestures";
import type {
  InAppNotification,
  InAppNotificationAction,
} from "../types/inapp-notification-types";
import { NotificationCardHeader } from "./notification-card-header";
import { NotificationInlineActions } from "./notification-card-inline-actions";
import {
  NotificationSwipeReadAction,
  NotificationSwipeRightActions,
} from "./notification-card-swipe-actions";

interface NotificationCardProps {
  notification: InAppNotification;
  onMarkAsRead: (notificationId: string) => void;
  onDismiss?: (notificationId: string) => void;
  onArchive?: (notificationId: string) => void;
  onSnooze?: (notificationId: string) => void;
  onActionPress: (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ) => void;
  isMarkingAsRead?: boolean;
  isActionLoading?: (actionId: string) => boolean;
  isSelectMode?: boolean;
  isSelected?: boolean;
  onLongPress?: (notificationId: string) => void;
  onSelectToggle?: (notificationId: string) => void;
}

export function NotificationCard({
  notification,
  onMarkAsRead,
  onDismiss,
  onArchive,
  onSnooze,
  onActionPress,
  isMarkingAsRead = false,
  isActionLoading,
  isSelectMode = false,
  isSelected = false,
  onLongPress,
  onSelectToggle,
}: NotificationCardProps) {
  const isUnread = notification.status !== "read";
  // Redirect actions are handled by tapping the whole card — they shouldn't
  // also render as an explicit chip. Only non-redirect actions (api_call,
  // workflow, modal) need a dedicated button.
  const inlineActions =
    notification.content.actions?.filter((a) => a.type !== "redirect") ?? [];
  const hasInlineActions = inlineActions.length > 0;

  const {
    swipeableRef,
    handleMarkAsRead,
    handleDismiss,
    handleArchive,
    handleSnooze,
    handleTap,
    handleLongPress,
    handleSwipeableOpen,
  } = useNotificationCardGestures({
    notification,
    isUnread,
    isSelectMode,
    onMarkAsRead,
    onDismiss,
    onArchive,
    onSnooze,
    onLongPress,
    onSelectToggle,
  });

  // Web background tones (EnhancedNotificationCard.tsx line 100):
  //   isUnread → bg-zinc-800/70  (zinc-800 = #27272a → rgba(39,39,42,0.7))
  //   read     → bg-zinc-800/30
  //   selected → primary tint
  const cardBg = isSelected
    ? "rgba(0,187,255,0.10)"
    : isUnread
      ? "rgba(39,39,42,0.70)"
      : "rgba(39,39,42,0.30)";

  return (
    <Swipeable
      ref={swipeableRef}
      enabled={!isSelectMode}
      friction={2}
      rightThreshold={60}
      leftThreshold={60}
      renderRightActions={
        onArchive || onDismiss || onSnooze
          ? (progress) => (
              <NotificationSwipeRightActions
                progress={progress}
                onSnooze={onSnooze && handleSnooze}
                onArchive={onArchive && handleArchive}
                onDismiss={handleDismiss}
              />
            )
          : undefined
      }
      renderLeftActions={
        isUnread
          ? (progress) => <NotificationSwipeReadAction progress={progress} />
          : undefined
      }
      onSwipeableOpen={handleSwipeableOpen}
    >
      {/* Wrap in plain View so the Pressable's transform isn't on the
          layout-animated parent — silences the Reanimated warning:
          "Property 'transform' of AnimatedComponent(View) may be overwritten
          by a layout animation." */}
      <View collapsable={false}>
        <Pressable
          onPress={handleTap}
          onLongPress={handleLongPress}
          accessible
          accessibilityRole="button"
          accessibilityLabel={notification.content.title}
          accessibilityState={{ selected: isSelected }}
          // Web: rounded-2xl (16px), px-4 py-3.5
          style={{
            borderRadius: 16,
            backgroundColor: cardBg,
            paddingHorizontal: 16,
            paddingVertical: 14,
            gap: 0,
            borderWidth: isSelected ? 1.5 : 0,
            borderColor: isSelected ? "#00bbff" : "transparent",
          }}
        >
          <NotificationCardHeader
            notification={notification}
            isUnread={isUnread}
            isSelectMode={isSelectMode}
            isSelected={isSelected}
            isMarkingAsRead={isMarkingAsRead}
            onMarkAsRead={handleMarkAsRead}
          />

          {/* Inline actions row — only renders for non-redirect action types.
              Redirect intent is satisfied by tapping the whole card, so
              showing it as an explicit chip is redundant chrome. */}
          {hasInlineActions && !isSelectMode && (
            <NotificationInlineActions
              notification={notification}
              actions={inlineActions}
              isUnread={isUnread}
              isActionLoading={isActionLoading}
              onActionPress={onActionPress}
            />
          )}
        </Pressable>
      </View>
    </Swipeable>
  );
}
