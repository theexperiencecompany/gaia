import * as Notifications from "expo-notifications";
import { useCallback, useEffect, useState } from "react";
import { type UseWebSocketOptions, useWebSocket } from "@/hooks/use-websocket";
import {
  isNotificationDelivered,
  isNotificationRead,
  isNotificationUpdated,
  type NotificationDeliveredMessage,
  type NotificationMessage,
  type WebSocketState,
} from "@/lib/websocket-client";

export interface RealtimeNotification {
  id: string;
  title: string;
  body: string;
  data?: Record<string, unknown>;
  receivedAt: Date;
}

export interface UseRealtimeNotificationsOptions {
  /** Show local push notification when receiving via WebSocket (default: true) */
  showLocalNotification?: boolean;
  /** Called when a new notification is received */
  onNotificationReceived?: (notification: RealtimeNotification) => void;
  /** Called when a notification is marked as read (from another device) */
  onNotificationRead?: (notificationId: string) => void;
  /** Called when a notification is updated */
  onNotificationUpdated?: (
    notificationId: string,
    updates: Record<string, unknown>,
  ) => void;
  /** WebSocket configuration options */
  websocketConfig?: Omit<UseWebSocketOptions, "onNotification" | "onMessage">;
}

export interface UseRealtimeNotificationsReturn {
  /** WebSocket connection state */
  connectionState: WebSocketState;
  /** Whether connected to real-time notifications */
  isConnected: boolean;
  /** Count of unread notifications (only from current session) */
  unreadCount: number;
  /** Recent notifications received in this session */
  recentNotifications: RealtimeNotification[];
  /** Manually connect to real-time notifications */
  connect: () => Promise<void>;
  /** Manually disconnect from real-time notifications */
  disconnect: () => void;
  /** Clear recent notifications */
  clearRecent: () => void;
  /** Mark a notification as read locally (decrements unread count) */
  markAsReadLocally: (notificationId: string) => void;
}

/**
 * Hook for receiving real-time notifications via WebSocket.
 *
 * This hook listens for notification broadcasts from the backend and optionally
 * shows them as local push notifications. It integrates with the existing
 * push notification system.
 *
 * @example
 * ```tsx
 * function App() {
 *   const {
 *     isConnected,
 *     unreadCount,
 *     recentNotifications
 *   } = useRealtimeNotifications({
 *     onNotificationReceived: (notification) => {
 *       console.log('New notification:', notification.title);
 *     },
 *   });
 *
 *   return (
 *     <View>
 *       <Text>Real-time: {isConnected ? '🟢' : '🔴'}</Text>
 *       <Text>Unread: {unreadCount}</Text>
 *     </View>
 *   );
 * }
 * ```
 */
export function useRealtimeNotifications(
  options: UseRealtimeNotificationsOptions = {},
): UseRealtimeNotificationsReturn {
  const {
    showLocalNotification = true,
    onNotificationReceived,
    onNotificationRead,
    onNotificationUpdated,
    websocketConfig = {},
  } = options;

  const [recentNotifications, setRecentNotifications] = useState<
    RealtimeNotification[]
  >([]);
  const [readNotificationIds, setReadNotificationIds] = useState<Set<string>>(
    new Set(),
  );

  const handleNotification = useCallback(
    async (message: NotificationMessage) => {
      if (isNotificationDelivered(message)) {
        const { notification } = message as NotificationDeliveredMessage;

        const realtimeNotification: RealtimeNotification = {
          id: notification.id,
          title: notification.title || "New Notification",
          body: notification.body || "",
          data: notification as Record<string, unknown>,
          receivedAt: new Date(),
        };

        // Add to recent notifications
        setRecentNotifications((prev) =>
          [realtimeNotification, ...prev].slice(0, 50),
        );

        // Optionally show local push notification
        if (showLocalNotification) {
          try {
            await Notifications.scheduleNotificationAsync({
              content: {
                title: realtimeNotification.title,
                body: realtimeNotification.body,
                data: {
                  notificationId: notification.id,
                  ...realtimeNotification.data,
                },
              },
              trigger: null, // Show immediately
            });
          } catch (error) {
            console.error(
              "[RealtimeNotifications] Failed to show local notification:",
              error,
            );
          }
        }

        // Call user callback
        onNotificationReceived?.(realtimeNotification);
      } else if (isNotificationRead(message)) {
        const { notification_id } = message;

        // Track as read
        setReadNotificationIds((prev) => new Set(prev).add(notification_id));

        // Call user callback
        onNotificationRead?.(notification_id);
      } else if (isNotificationUpdated(message)) {
        const { notification_id, updates } = message;

        // Update the notification in our recent list
        setRecentNotifications((prev) =>
          prev.map((n) =>
            n.id === notification_id
              ? { ...n, data: { ...n.data, ...updates } }
              : n,
          ),
        );

        // Call user callback
        onNotificationUpdated?.(notification_id, updates);
      }
    },
    [
      showLocalNotification,
      onNotificationReceived,
      onNotificationRead,
      onNotificationUpdated,
    ],
  );

  const {
    state: connectionState,
    isConnected,
    connect,
    disconnect,
  } = useWebSocket({
    ...websocketConfig,
    onNotification: handleNotification,
  });

  const clearRecent = useCallback(() => {
    setRecentNotifications([]);
    setReadNotificationIds(new Set());
  }, []);

  const markAsReadLocally = useCallback((notificationId: string) => {
    setReadNotificationIds((prev) => new Set(prev).add(notificationId));
  }, []);

  // Calculate unread count
  const unreadCount = recentNotifications.filter(
    (n) => !readNotificationIds.has(n.id),
  ).length;

  // Clear notifications on disconnect
  useEffect(() => {
    if (!isConnected) {
      // Optionally clear recent notifications when disconnected
      // Uncomment if you want this behavior:
      // setRecentNotifications([]);
    }
  }, [isConnected]);

  return {
    connectionState,
    isConnected,
    unreadCount,
    recentNotifications,
    connect,
    disconnect,
    clearRecent,
    markAsReadLocally,
  };
}
