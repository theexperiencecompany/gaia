import { parseRelativeDateLabel } from "@gaia/shared/utils";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useRef } from "react";
import { Animated, Pressable, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import type { AnyIcon } from "@/components/icons";
import {
  AlertCircleIcon,
  AppIcon,
  Cancel01Icon,
  CheckmarkBadge01Icon,
  CheckmarkCircle02Icon,
  FolderIcon,
  LinkSquare02Icon,
  Timer02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type {
  InAppNotification,
  InAppNotificationAction,
  NotificationActionType,
} from "../types/inapp-notification-types";

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

function getActionIcon(type: NotificationActionType): AnyIcon | null {
  switch (type) {
    case "redirect":
      return LinkSquare02Icon;
    case "api_call":
      return CheckmarkCircle02Icon;
    case "workflow":
      return Timer02Icon;
    case "modal":
      return AlertCircleIcon;
    default:
      return null;
  }
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
  const router = useRouter();
  const swipeableRef = useRef<Swipeable>(null);
  const isUnread = notification.status !== "read";
  // Redirect actions are handled by tapping the whole card — they shouldn't
  // also render as an explicit chip. Only non-redirect actions (api_call,
  // workflow, modal) need a dedicated button.
  const inlineActions =
    notification.content.actions?.filter((a) => a.type !== "redirect") ?? [];
  const hasInlineActions = inlineActions.length > 0;

  const handleMarkAsRead = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    swipeableRef.current?.close();
    onMarkAsRead(notification.id);
  }, [onMarkAsRead, notification.id]);

  const handleDismiss = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    swipeableRef.current?.close();
    onDismiss?.(notification.id);
  }, [onDismiss, notification.id]);

  const handleArchive = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    swipeableRef.current?.close();
    onArchive?.(notification.id);
  }, [onArchive, notification.id]);

  const handleSnooze = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    swipeableRef.current?.close();
    onSnooze?.(notification.id);
  }, [onSnooze, notification.id]);

  const handleTap = useCallback(() => {
    if (isSelectMode) {
      onSelectToggle?.(notification.id);
      return;
    }
    const redirectAction = notification.content.actions?.find(
      (a) => a.type === "redirect" && a.config.redirect?.url,
    );
    if (redirectAction?.config.redirect?.url) {
      const url = redirectAction.config.redirect.url;
      if (url.startsWith("/")) router.push(url as never);
    }
    if (isUnread) onMarkAsRead(notification.id);
  }, [
    notification,
    isUnread,
    onMarkAsRead,
    router,
    isSelectMode,
    onSelectToggle,
  ]);

  const handleLongPress = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onLongPress?.(notification.id);
  }, [onLongPress, notification.id]);

  const renderLeftActions = useCallback(
    (progress: Animated.AnimatedInterpolation<number>) => {
      const translateX = progress.interpolate({
        inputRange: [0, 1],
        outputRange: [-76, 0],
      });
      return (
        <Animated.View
          style={{
            transform: [{ translateX }],
            justifyContent: "center",
            alignItems: "flex-end",
            width: 76,
            paddingRight: 6,
          }}
        >
          <View
            style={{
              width: 64,
              height: "100%",
              backgroundColor: "rgba(0,187,255,0.12)",
              borderRadius: 16,
              justifyContent: "center",
              alignItems: "center",
              gap: 4,
            }}
          >
            <AppIcon icon={CheckmarkBadge01Icon} size={18} color="#00bbff" />
            <Text style={{ fontSize: 10, color: "#00bbff" }}>Read</Text>
          </View>
        </Animated.View>
      );
    },
    [],
  );

  const renderRightActions = useCallback(
    (progress: Animated.AnimatedInterpolation<number>) => {
      const hasSnooze = !!onSnooze;
      const totalWidth = hasSnooze ? 156 : 76;
      const translateX = progress.interpolate({
        inputRange: [0, 1],
        outputRange: [totalWidth, 0],
      });
      return (
        <Animated.View
          style={{
            transform: [{ translateX }],
            justifyContent: "center",
            alignItems: "flex-start",
            width: totalWidth,
            flexDirection: "row",
            gap: hasSnooze ? 8 : 0,
            paddingLeft: 6,
          }}
        >
          {hasSnooze && (
            <Pressable
              onPress={handleSnooze}
              style={{
                width: 64,
                height: "100%",
                backgroundColor: "rgba(251,191,36,0.16)",
                borderRadius: 16,
                justifyContent: "center",
                alignItems: "center",
                gap: 4,
              }}
            >
              <AppIcon icon={Timer02Icon} size={18} color="#fbbf24" />
              <Text style={{ fontSize: 10, color: "#fbbf24" }}>Snooze</Text>
            </Pressable>
          )}
          <Pressable
            onPress={onArchive ? handleArchive : handleDismiss}
            style={{
              width: 64,
              height: "100%",
              backgroundColor: onArchive
                ? "rgba(63,63,70,0.6)"
                : "rgba(239,68,68,0.12)",
              borderRadius: 16,
              justifyContent: "center",
              alignItems: "center",
              gap: 4,
            }}
          >
            {onArchive ? (
              <>
                <AppIcon icon={FolderIcon} size={18} color="#a1a1aa" />
                <Text style={{ fontSize: 10, color: "#a1a1aa" }}>Archive</Text>
              </>
            ) : (
              <>
                <AppIcon icon={Cancel01Icon} size={18} color="#ef4444" />
                <Text style={{ fontSize: 10, color: "#ef4444" }}>Dismiss</Text>
              </>
            )}
          </Pressable>
        </Animated.View>
      );
    },
    [handleArchive, handleDismiss, handleSnooze, onArchive, onSnooze],
  );

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
        onArchive || onDismiss || onSnooze ? renderRightActions : undefined
      }
      renderLeftActions={isUnread ? renderLeftActions : undefined}
      onSwipeableOpen={(direction) => {
        // Long swipe-left (renders right-side actions) → archive directly,
        // matching the spec's "long swipe commits without tap".
        if (direction === "right") {
          if (onArchive) handleArchive();
          else handleDismiss();
        } else if (direction === "left" && isUnread) {
          handleMarkAsRead();
        }
      }}
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
          {/* Top row: title + body block, mark-as-read button */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            {/* Selection checkbox */}
            {isSelectMode && (
              <View
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 11,
                  borderWidth: 2,
                  borderColor: isSelected ? "#00bbff" : "#48484a",
                  backgroundColor: isSelected
                    ? "rgba(0,187,255,0.20)"
                    : "transparent",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  marginTop: 2,
                }}
              >
                {isSelected && (
                  <AppIcon
                    icon={CheckmarkCircle02Icon}
                    size={14}
                    color="#00bbff"
                  />
                )}
              </View>
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
                    onPress={handleMarkAsRead}
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
                    <AppIcon
                      icon={CheckmarkBadge01Icon}
                      size={16}
                      color="#71717a"
                    />
                  </Pressable>
                )}
              </View>
            )}
          </View>

          {/* Inline actions row — only renders for non-redirect action types.
              Redirect intent is satisfied by tapping the whole card, so
              showing it as an explicit chip is redundant chrome. */}
          {hasInlineActions && !isSelectMode && (
            <View
              style={{
                marginTop: 12,
                flexDirection: "row",
                flexWrap: "wrap",
                gap: 8,
                opacity: isUnread ? 1 : 0.6,
              }}
            >
              {inlineActions.map((action) => {
                const loading = isActionLoading?.(action.id) ?? false;
                const executed = action.executed ?? false;
                const showLoading = loading && action.type !== "modal";
                const tone = getActionTone(action.style);
                const trailingIcon = executed
                  ? CheckmarkCircle02Icon
                  : getActionIcon(action.type);
                return (
                  <Pressable
                    key={action.id}
                    disabled={loading || action.disabled || executed}
                    onPress={() => onActionPress(notification, action)}
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
                          <AppIcon
                            icon={trailingIcon}
                            size={12}
                            color={tone.text}
                          />
                        )}
                      </>
                    )}
                  </Pressable>
                );
              })}
            </View>
          )}
        </Pressable>
      </View>
    </Swipeable>
  );
}
