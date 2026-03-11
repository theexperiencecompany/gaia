import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useRef } from "react";
import { Animated, Pressable, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import {
  Calendar03Icon,
  Cancel01Icon,
  CheckmarkSquare03Icon,
  HugeiconsIcon,
  Mail01Icon,
  Notification01Icon,
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

type NotificationIconType =
  | typeof Notification01Icon
  | typeof Mail01Icon
  | typeof Calendar03Icon
  | typeof CheckmarkSquare03Icon;

function getNotificationIcon(
  source?: string,
  type?: string,
): NotificationIconType {
  const key = (source ?? type ?? "").toLowerCase();

  if (key.includes("email") || key.includes("mail")) return Mail01Icon;
  if (key.includes("calendar") || key.includes("event")) return Calendar03Icon;
  if (key.includes("todo") || key.includes("task"))
    return CheckmarkSquare03Icon;

  return Notification01Icon;
}

function getIconAccentColor(source?: string, type?: string): string {
  const key = (source ?? type ?? "").toLowerCase();

  if (key.includes("email") || key.includes("mail")) return "#60a5fa";
  if (key.includes("calendar") || key.includes("event")) return "#a78bfa";
  if (key.includes("todo") || key.includes("task")) return "#4ade80";

  return "#00bbff";
}

export function NotificationCard({
  notification,
  onMarkAsRead,
  onDismiss,
  onActionPress,
  isMarkingAsRead = false,
  isActionLoading,
}: NotificationCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const router = useRouter();
  const swipeableRef = useRef<Swipeable>(null);
  const isUnread = notification.status !== "read";

  const iconComponent = getNotificationIcon(
    notification.source,
    notification.type,
  );
  const accentColor = getIconAccentColor(
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

  const handleTap = useCallback(() => {
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
  }, [notification, isUnread, onMarkAsRead, router]);

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
            style={{
              width: 64,
              height: "100%",
              backgroundColor: "rgba(0,187,255,0.14)",
              borderRadius: moderateScale(16, 0.5),
              justifyContent: "center",
              alignItems: "center",
              gap: 4,
            }}
          >
            <HugeiconsIcon icon={Tick02Icon} size={18} color="#00bbff" />
            <Text style={{ fontSize: fontSize.xs - 1, color: "#00bbff" }}>
              Read
            </Text>
          </Pressable>
        </Animated.View>
      );
    },
    [handleMarkAsRead, moderateScale, fontSize.xs],
  );

  const renderRightActions = useCallback(
    (progress: Animated.AnimatedInterpolation<number>) => {
      const translateX = progress.interpolate({
        inputRange: [0, 1],
        outputRange: [80, 0],
      });

      return (
        <Animated.View
          style={{
            transform: [{ translateX }],
            justifyContent: "center",
            alignItems: "flex-start",
            width: 80,
          }}
        >
          <Pressable
            onPress={handleDismiss}
            style={{
              width: 64,
              height: "100%",
              backgroundColor: "rgba(239,68,68,0.12)",
              borderRadius: moderateScale(16, 0.5),
              justifyContent: "center",
              alignItems: "center",
              gap: 4,
            }}
          >
            <HugeiconsIcon icon={Cancel01Icon} size={18} color="#ef4444" />
            <Text style={{ fontSize: fontSize.xs - 1, color: "#ef4444" }}>
              Dismiss
            </Text>
          </Pressable>
        </Animated.View>
      );
    },
    [handleDismiss, moderateScale, fontSize.xs],
  );

  return (
    <Swipeable
      ref={swipeableRef}
      friction={2}
      leftThreshold={60}
      rightThreshold={60}
      renderLeftActions={isUnread ? renderLeftActions : undefined}
      renderRightActions={onDismiss ? renderRightActions : undefined}
      onSwipeableOpen={(direction) => {
        if (direction === "left" && isUnread) {
          void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
          handleMarkAsRead();
        } else if (direction === "right") {
          handleDismiss();
        }
      }}
    >
      <Pressable onPress={handleTap}>
        <View
          style={{
            borderRadius: moderateScale(16, 0.5),
            backgroundColor: isUnread ? "#1c1f26" : "#171920",
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
              backgroundColor: `${accentColor}18`,
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              marginTop: 1,
            }}
          >
            <HugeiconsIcon icon={iconComponent} size={17} color={accentColor} />
          </View>

          {/* Main content */}
          <View style={{ flex: 1, minWidth: 0 }}>
            {/* Title row */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                gap: spacing.sm,
              }}
            >
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  flex: 1,
                  minWidth: 0,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: "600",
                    color: isUnread ? "#e8ebef" : "#8e8e93",
                    flexShrink: 1,
                  }}
                  numberOfLines={2}
                >
                  {notification.content.title}
                </Text>
                {isUnread && (
                  <View
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 3.5,
                      backgroundColor: "#00bbff",
                      flexShrink: 0,
                    }}
                  />
                )}
              </View>

              {/* Mark as read */}
              {isUnread && (
                <Pressable
                  disabled={isMarkingAsRead}
                  onPress={handleMarkAsRead}
                  hitSlop={10}
                  style={{ opacity: isMarkingAsRead ? 0.4 : 0.6 }}
                >
                  <HugeiconsIcon icon={Tick02Icon} size={15} color="#8e8e93" />
                </Pressable>
              )}
            </View>

            {/* Body */}
            {!!notification.content.body && (
              <Text
                style={{
                  fontSize: fontSize.xs + 1,
                  color: isUnread ? "#c5cad2" : "#636366",
                  lineHeight: (fontSize.xs + 1) * 1.45,
                  marginTop: 3,
                }}
              >
                {notification.content.body}
              </Text>
            )}

            {/* Actions + timestamp */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "flex-end",
                justifyContent: "space-between",
                marginTop: spacing.sm,
              }}
            >
              <View
                style={{
                  flexDirection: "row",
                  flexWrap: "wrap",
                  gap: spacing.xs,
                  flex: 1,
                  opacity: isUnread ? 1 : 0.55,
                }}
              >
                {notification.content.actions?.map((action) => {
                  const actionLoading = isActionLoading?.(action.id) ?? false;
                  const isExecuted = action.executed ?? false;
                  const aStyle = getActionStyle(action.style);

                  return (
                    <Pressable
                      key={action.id}
                      disabled={actionLoading || action.disabled || isExecuted}
                      onPress={() => onActionPress(notification, action)}
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

              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  color: "#48484a",
                  flexShrink: 0,
                  marginLeft: spacing.sm,
                }}
              >
                {formatDate(notification.created_at)}
              </Text>
            </View>
          </View>
        </View>
      </Pressable>
    </Swipeable>
  );
}
