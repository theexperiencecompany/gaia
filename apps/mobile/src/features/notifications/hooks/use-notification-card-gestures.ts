import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useRef } from "react";
import type { Swipeable } from "react-native-gesture-handler";
import type { InAppNotification } from "../types/inapp-notification-types";

type NotificationIdHandler = (notificationId: string) => void;

interface UseNotificationCardGesturesParams {
  notification: InAppNotification;
  isUnread: boolean;
  isSelectMode: boolean;
  onMarkAsRead: NotificationIdHandler;
  onDismiss?: NotificationIdHandler;
  onArchive?: NotificationIdHandler;
  onSnooze?: NotificationIdHandler;
  onLongPress?: NotificationIdHandler;
  onSelectToggle?: NotificationIdHandler;
}

/**
 * Tap, long-press and swipe handlers for a notification card. Each swipe
 * commit closes the row and fires haptics before delegating to the caller.
 */
export function useNotificationCardGestures({
  notification,
  isUnread,
  isSelectMode,
  onMarkAsRead,
  onDismiss,
  onArchive,
  onSnooze,
  onLongPress,
  onSelectToggle,
}: UseNotificationCardGesturesParams) {
  const router = useRouter();
  const swipeableRef = useRef<Swipeable>(null);

  const handleMarkAsRead = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    swipeableRef.current?.close();
    onMarkAsRead(notification.id);
  };

  const handleDismiss = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    swipeableRef.current?.close();
    onDismiss?.(notification.id);
  };

  const handleArchive = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    swipeableRef.current?.close();
    onArchive?.(notification.id);
  };

  const handleSnooze = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    swipeableRef.current?.close();
    onSnooze?.(notification.id);
  };

  const handleTap = () => {
    if (isSelectMode) {
      onSelectToggle?.(notification.id);
      return;
    }
    const redirectAction = notification.content.actions?.find(
      (a) => a.type === "redirect" && a.config?.redirect?.url,
    );
    const url = redirectAction?.config?.redirect?.url;
    if (url) {
      if (url.startsWith("/")) router.push(url as never);
    }
    if (isUnread) onMarkAsRead(notification.id);
  };

  const handleLongPress = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onLongPress?.(notification.id);
  };

  // Long swipe-left (renders right-side actions) → archive directly,
  // matching the spec's "long swipe commits without tap".
  const handleSwipeableOpen = (direction: "left" | "right") => {
    if (direction === "right") {
      if (onArchive) handleArchive();
      else handleDismiss();
    } else if (direction === "left" && isUnread) {
      handleMarkAsRead();
    }
  };

  return {
    swipeableRef,
    handleMarkAsRead,
    handleDismiss,
    handleArchive,
    handleSnooze,
    handleTap,
    handleLongPress,
    handleSwipeableOpen,
  };
}
