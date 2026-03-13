import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useRef } from "react";
import { Animated, Pressable, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import type { AnyIcon } from "@/components/icons";
import {
  AlarmClockIcon,
  AppIcon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  CheckmarkSquare03Icon,
  ConnectIcon,
  FlashIcon,
  FolderIcon,
  InformationCircleIcon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type {
  InAppNotification,
  InAppNotificationAction,
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

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Now";
  }

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function getActionStyle(style?: string): {
  bg: string;
  text: string;
} {
  switch (style) {
    case "primary":
      return { bg: "rgba(0,187,255,0.12)", text: "#00bbff" };
    case "danger":
      return { bg: "rgba(239,68,68,0.1)", text: "#ef4444" };
    default:
      return { bg: "rgba(255,255,255,0.06)", text: "#c5cad2" };
  }
}

type NotificationIconConfig = {
  icon: AnyIcon;
  color: string;
};

function getNotificationIconConfig(
  source?: string,
  type?: string,
): NotificationIconConfig {
  const key = (source ?? type ?? "").toLowerCase();

  if (key.includes("workflow") || key.includes("automation")) {
    return { icon: FlashIcon, color: "#a78bfa" };
  }
  if (
    key.includes("reminder") ||
    key.includes("alarm") ||
    key.includes("schedule")
  ) {
    return { icon: AlarmClockIcon, color: "#fbbf24" };
  }
  if (
    key.includes("integration") ||
    key.includes("connect") ||
    key.includes("plugin")
  ) {
    return { icon: ConnectIcon, color: "#34d399" };
  }
  if (
    key.includes("system") ||
    key.includes("info") ||
    key.includes("notice")
  ) {
    return { icon: InformationCircleIcon, color: "#60a5fa" };
  }
  if (key.includes("email") || key.includes("mail")) {
    return { icon: CheckmarkSquare03Icon, color: "#60a5fa" };
  }
  if (key.includes("todo") || key.includes("task")) {
    return { icon: CheckmarkSquare03Icon, color: "#4ade80" };
  }

  // Default: system info icon
  return { icon: InformationCircleIcon, color: "#00bbff" };
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
  const { spacing, fontSize, moderateScale } = useResponsive();
  const router = useRouter();
  const swipeableRef = useRef<Swipeable>(null);
  const isUnread = notification.status !== "read";

  const iconConfig = getNotificationIconConfig(
    notification.source,
    notification.type,
  );

  const handleMarkAsRead = useCallback(() => {
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
      if (url.startsWith("/")) {
        router.push(url as never);
      }
    }
    if (isUnread) {
      onMarkAsRead(notification.id);
    }
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

  // Swipe right → mark as read (green)
  const renderLeftActions = useCallback(
    (progress: Animated.AnimatedInterpolation<number>) => {
      const translateX = progress.interpolate({
        inputRange: [0, 1],
        outputRange: [-80, 0],
      });

      return (
        <Animated.View
          style={{
            transform: [{ translateX }],
            justifyContent: "center",
            alignItems: "flex-end",
            width: 80,
          }}
        >
          <Pressable
            onPress={handleMarkAsRead}
            disabled={isMarkingAsRead}
            style={{
              width: 64,
              height: "100%",
              backgroundColor: "rgba(52,199,89,0.18)",
              borderRadius: moderateScale(16, 0.5),
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon icon={Tick02Icon} size={18} color="#34c759" />
            <Text style={{ fontSize: fontSize.xs - 1, color: "#34c759" }}>
              Read
            </Text>
          </Pressable>{" "}
        </Animated.View>
      );
    },
    [handleMarkAsRead, isMarkingAsRead, moderateScale, fontSize.xs],
  );

  // Swipe left → snooze (amber) + archive/dismiss (blue/red)
  const renderRightActions = useCallback(
    (progress: Animated.AnimatedInterpolation<number>) => {
      const hasSnoozeAction = !!onSnooze;
      const totalWidth = hasSnoozeAction ? 164 : 80;

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
            gap: hasSnoozeAction ? 8 : 0,
          }}
        >
          {hasSnoozeAction && (
            <Pressable
              onPress={handleSnooze}
              style={{
                width: 64,
                height: "100%",
                backgroundColor: "rgba(251,191,36,0.18)",
                borderRadius: moderateScale(16, 0.5),
                justifyContent: "center",
                alignItems: "center",
                gap: 4,
              }}
            >
              <AppIcon icon={AlarmClockIcon} size={18} color="#fbbf24" />
              <Text style={{ fontSize: fontSize.xs - 1, color: "#fbbf24" }}>
                Snooze
              </Text>
            </Pressable>
          )}
          <Pressable
            onPress={onArchive ? handleArchive : handleDismiss}
            style={{
              width: 64,
              height: "100%",
              backgroundColor: onArchive
                ? "rgba(59,130,246,0.18)"
                : "rgba(239,68,68,0.12)",
              borderRadius: moderateScale(16, 0.5),
            }}
          >
            {onArchive ? (
              <>
                <AppIcon icon={FolderIcon} size={18} color="#3b82f6" />
                <Text style={{ fontSize: fontSize.xs - 1, color: "#3b82f6" }}>
                  Archive
                </Text>
              </>
            ) : (
              <>
                <AppIcon icon={Cancel01Icon} size={18} color="#ef4444" />
                <Text style={{ fontSize: fontSize.xs - 1, color: "#ef4444" }}>
                  Dismiss
                </Text>
              </>
            )}
          </Pressable>{" "}
        </Animated.View>
      );
    },
    [
      handleArchive,
      handleDismiss,
      handleSnooze,
      onArchive,
      onSnooze,
      moderateScale,
      fontSize.xs,
    ],
  );

  const hasActions =
    notification.content.actions && notification.content.actions.length > 0;

  return (
    <Swipeable
      ref={swipeableRef}
      enabled={!isSelectMode}
      friction={2}
      leftThreshold={60}
      rightThreshold={60}
      renderLeftActions={isUnread ? renderLeftActions : undefined}
      renderRightActions={
        onArchive || onDismiss || onSnooze ? renderRightActions : undefined
      }
      onSwipeableOpen={(direction) => {
        if (direction === "left" && isUnread) {
          void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
          handleMarkAsRead();
        } else if (direction === "right") {
          if (onArchive) {
            handleArchive();
          } else {
            handleDismiss();
          }
        }
      }}
    >
      <Pressable
        onPress={handleTap}
        onLongPress={handleLongPress}
        accessible={true}
        accessibilityRole="button"
        accessibilityLabel={notification.content.title}
        accessibilityHint={
          isSelectMode
            ? isSelected
              ? "Double tap to deselect"
              : "Double tap to select"
            : "Double tap to open notification"
        }
        accessibilityState={{ selected: isSelected }}
      >
        <View
          style={{
            borderRadius: moderateScale(16, 0.5),
            backgroundColor: isUnread ? "#1c1f26" : "#171920",
            padding: spacing.md,
            flexDirection: "row",
            alignItems: "flex-start",
            gap: spacing.sm,
            borderWidth: isSelected ? 1.5 : 0,
            borderColor: isSelected ? "#00bbff" : "transparent",
            // Left accent border for unread notifications
            borderLeftWidth: isUnread && !isSelected ? 3 : isSelected ? 1.5 : 0,
            borderLeftColor:
              isUnread && !isSelected
                ? iconConfig.color
                : isSelected
                  ? "#00bbff"
                  : "transparent",
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
                  ? "rgba(0,187,255,0.2)"
                  : "transparent",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                marginTop: 7,
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

          {/* Type icon pill */}
          <View
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              backgroundColor: `${iconConfig.color}18`,
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              marginTop: 1,
            }}
          >
            <AppIcon
              icon={iconConfig.icon}
              size={17}
              color={iconConfig.color}
            />
          </View>

          {/* Main content */}
          <View style={{ flex: 1, minWidth: 0 }}>
            {/* Title row */}{" "}
            <View
              style={{
                padding: spacing.md,
                flexDirection: "row",
                alignItems: "flex-start",
                gap: spacing.sm,
              }}
            >
              {/* Source icon pill */}
              <View
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 10,
                  backgroundColor: `${iconConfig.color}18`,
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  marginTop: 1,
                }}
              >
                {/* Unread dot indicator */}
                {isUnread && (
                  <View
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 3.5,
                      backgroundColor: iconConfig.color,
                      flexShrink: 0,
                    }}
                  />
                )}
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: isUnread ? "600" : "400",
                    color: isUnread ? "#e8ebef" : "#8e8e93",
                    flexShrink: 1,
                  }}
                >
                  {notification.content.title}
                </Text>
              </View>

              {/* Mark as read button */}
              {isUnread && !isSelectMode && (
                <Pressable
                  disabled={isMarkingAsRead}
                  onPress={handleMarkAsRead}
                  hitSlop={10}
                  style={{ opacity: isMarkingAsRead ? 0.4 : 0.6 }}
                  accessibilityRole="button"
                  accessibilityLabel="Mark as read"
                  accessibilityState={{ disabled: isMarkingAsRead }}
                >
                  <AppIcon icon={Tick02Icon} size={15} color="#8e8e93" />
                </Pressable>
              )}
            </View>
            {/* Body — max 2 lines */}
            {!!notification.content.body && (
              <Text
                style={{
                  fontSize: fontSize.xs + 1,
                  color: isUnread ? "#c5cad2" : "#636366",
                  lineHeight: (fontSize.xs + 1) * 1.45,
                  marginTop: 3,
                }}
                numberOfLines={2}
              >
                {notification.content.body}
              </Text>
            )}
            {/* Actions row */}
            {hasActions && (
              <View
                style={{
                  flexDirection: "row",
                  flexWrap: "wrap",
                  gap: spacing.xs,
                  marginTop: spacing.sm,
                  opacity: isUnread ? 1 : 0.55,
                }}
              >
                {!isSelectMode &&
                  notification.content.actions?.map((action) => {
                    const actionLoading = isActionLoading?.(action.id) ?? false;
                    const isExecuted = action.executed ?? false;
                    const aStyle = getActionStyle(action.style);

                    return (
                      <Pressable
                        key={action.id}
                        disabled={
                          actionLoading || action.disabled || isExecuted
                        }
                        onPress={() => onActionPress(notification, action)}
                        accessibilityRole="button"
                        accessibilityLabel={action.label}
                        accessibilityState={{
                          disabled:
                            actionLoading ||
                            action.disabled === true ||
                            isExecuted,
                        }}
                        style={{
                          borderRadius: 8,
                          paddingHorizontal: spacing.sm + 4,
                          paddingVertical: 5,
                          backgroundColor: aStyle.bg,
                          opacity:
                            actionLoading || action.disabled || isExecuted
                              ? 0.5
                              : 1,
                        }}
                      >
                        <Text
                          style={{
                            fontSize: fontSize.xs,
                            color: aStyle.text,
                            fontWeight: "500",
                          }}
                        >
                          {actionLoading
                            ? "Working..."
                            : isExecuted
                              ? `${action.label} ✓`
                              : action.label}
                        </Text>
                      </Pressable>
                    );
                  })}
              </View>
            )}
            {/* Timestamp */}
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: "#48484a",
                marginTop: hasActions ? 4 : spacing.sm,
                alignSelf: "flex-end",
              }}
            >
              {formatDate(notification.created_at)}
            </Text>
          </View>
        </View>{" "}
      </Pressable>
    </Swipeable>
  );
}
