import * as Notifications from "expo-notifications";
import { useCallback, useEffect, useRef, useState } from "react";
import { wsManager } from "@/lib/websocket-client";
import { WS_EVENTS } from "@/lib/websocket-events";

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
}

export interface UseRealtimeNotificationsReturn {
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
 */
export function useRealtimeNotifications(
  options: UseRealtimeNotificationsOptions = {},
): UseRealtimeNotificationsReturn {
  const {
    showLocalNotification = true,
    onNotificationReceived,
    onNotificationRead,
    onNotificationUpdated,
  } = options;

  const [recentNotifications, setRecentNotifications] = useState<
    RealtimeNotification[]
  >([]);
  const [readNotificationIds, setReadNotificationIds] = useState<Set<string>>(
    new Set(),
  );
  const [isConnected, setIsConnected] = useState(wsManager.isConnected);

  // Keep stable refs for callbacks
  const onReceivedRef = useRef(onNotificationReceived);
  const onReadRef = useRef(onNotificationRead);
  const onUpdatedRef = useRef(onNotificationUpdated);
  useEffect(() => {
    onReceivedRef.current = onNotificationReceived;
    onReadRef.current = onNotificationRead;
    onUpdatedRef.current = onNotificationUpdated;
  }, [onNotificationReceived, onNotificationRead, onNotificationUpdated]);

  const showLocalRef = useRef(showLocalNotification);
  useEffect(() => {
    showLocalRef.current = showLocalNotification;
  }, [showLocalNotification]);

  useEffect(() => {
    const handleConnect = () => setIsConnected(true);
    const handleDisconnect = () => setIsConnected(false);

    wsManager.onConnect(handleConnect);
    wsManager.onDisconnect(handleDisconnect);

    const unsubDelivered = wsManager.subscribe(
      WS_EVENTS.NOTIFICATION_DELIVERED,
      (message: unknown) => {
        const msg = message as Record<string, unknown>;
        const notification = msg.notification as
          | Record<string, unknown>
          | undefined;
        if (!notification) return;

        const realtimeNotification: RealtimeNotification = {
          id:
            typeof notification.id === "string"
              ? notification.id
              : String(notification.id ?? ""),
          title:
            typeof notification.title === "string"
              ? notification.title
              : "New Notification",
          body: typeof notification.body === "string" ? notification.body : "",
          data: notification as Record<string, unknown>,
          receivedAt: new Date(),
        };

        setRecentNotifications((prev) =>
          [realtimeNotification, ...prev].slice(0, 50),
        );

        if (showLocalRef.current) {
          Notifications.scheduleNotificationAsync({
            content: {
              title: realtimeNotification.title,
              body: realtimeNotification.body,
              data: {
                notificationId: realtimeNotification.id,
                ...realtimeNotification.data,
              },
            },
            trigger: null,
          }).catch((error: unknown) => {
            console.error(
              "[RealtimeNotifications] Failed to show local notification:",
              error,
            );
          });
        }

        onReceivedRef.current?.(realtimeNotification);
      },
    );

    const unsubRead = wsManager.subscribe(
      WS_EVENTS.NOTIFICATION_READ,
      (message: unknown) => {
        const msg = message as Record<string, unknown>;
        const notificationId =
          typeof msg.notification_id === "string" ? msg.notification_id : null;
        if (!notificationId) return;

        setReadNotificationIds((prev) => new Set(prev).add(notificationId));
        onReadRef.current?.(notificationId);
      },
    );

    const unsubUpdated = wsManager.subscribe(
      WS_EVENTS.NOTIFICATION_UPDATED,
      (message: unknown) => {
        const msg = message as Record<string, unknown>;
        const notificationId =
          typeof msg.notification_id === "string" ? msg.notification_id : null;
        const updates =
          msg.updates && typeof msg.updates === "object"
            ? (msg.updates as Record<string, unknown>)
            : {};
        if (!notificationId) return;

        setRecentNotifications((prev) =>
          prev.map((n) =>
            n.id === notificationId
              ? { ...n, data: { ...n.data, ...updates } }
              : n,
          ),
        );
        onUpdatedRef.current?.(notificationId, updates);
      },
    );

    return () => {
      wsManager.offConnect(handleConnect);
      wsManager.offDisconnect(handleDisconnect);
      unsubDelivered();
      unsubRead();
      unsubUpdated();
    };
  }, []);

  const connect = useCallback(async () => {
    await wsManager.connect();
  }, []);

  const disconnect = useCallback(() => {
    wsManager.disconnect();
  }, []);

  const clearRecent = useCallback(() => {
    setRecentNotifications([]);
    setReadNotificationIds(new Set());
  }, []);

  const markAsReadLocally = useCallback((notificationId: string) => {
    setReadNotificationIds((prev) => new Set(prev).add(notificationId));
  }, []);

  const unreadCount = recentNotifications.filter(
    (n) => !readNotificationIds.has(n.id),
  ).length;

  return {
    isConnected,
    unreadCount,
    recentNotifications,
    connect,
    disconnect,
    clearRecent,
    markAsReadLocally,
  };
}
