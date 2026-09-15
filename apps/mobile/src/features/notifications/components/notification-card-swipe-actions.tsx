import { Animated, Pressable, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  CheckmarkBadge01Icon,
  FolderIcon,
  Timer02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

interface NotificationSwipeReadActionProps {
  progress: Animated.AnimatedInterpolation<number>;
}

/** Left-swipe reveal: the "Read" pill behind an unread card. */
export function NotificationSwipeReadAction({
  progress,
}: NotificationSwipeReadActionProps) {
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
}

interface NotificationSwipeRightActionsProps {
  progress: Animated.AnimatedInterpolation<number>;
  /** Renders a Snooze pill when provided. */
  onSnooze?: () => void;
  /** Turns the trailing pill into Archive; without it the pill dismisses. */
  onArchive?: () => void;
  onDismiss: () => void;
}

/** Right-swipe reveal: optional Snooze pill plus Archive (or Dismiss). */
export function NotificationSwipeRightActions({
  progress,
  onSnooze,
  onArchive,
  onDismiss,
}: NotificationSwipeRightActionsProps) {
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
      {onSnooze && (
        <Pressable
          onPress={onSnooze}
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
        onPress={onArchive ?? onDismiss}
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
}
