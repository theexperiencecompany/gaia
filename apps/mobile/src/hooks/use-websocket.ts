import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";
import { useAuth } from "@/features/auth/hooks/use-auth";
import {
  createWebSocketConnection,
  type NotificationMessage,
  type WebSocketCallbacks,
  type WebSocketConfig,
  type WebSocketController,
  type WebSocketMessage,
  type WebSocketState,
} from "@/lib/websocket-client";

export interface UseWebSocketOptions extends WebSocketConfig {
  /** Whether to auto-connect when authenticated (default: true) */
  autoConnect?: boolean;
  /** Handler for all WebSocket messages */
  onMessage?: (message: WebSocketMessage) => void;
  /** Handler for notification-specific messages */
  onNotification?: (message: NotificationMessage) => void;
  /** Handler for connection errors */
  onError?: (error: Error) => void;
}

export interface UseWebSocketReturn {
  /** Current connection state */
  state: WebSocketState;
  /** Whether connected to WebSocket */
  isConnected: boolean;
  /** Manually connect to WebSocket */
  connect: () => Promise<void>;
  /** Manually disconnect from WebSocket */
  disconnect: () => void;
  /** Last received message */
  lastMessage: WebSocketMessage | null;
  /** Last received notification message */
  lastNotification: NotificationMessage | null;
}

/**
 * React hook for managing WebSocket connection to the backend.
 * Automatically handles:
 * - Connection on auth state change
 * - Reconnection on app foregrounding
 * - Cleanup on unmount
 *
 * @example
 * ```tsx
 * function NotificationListener() {
 *   const { state, isConnected, lastNotification } = useWebSocket({
 *     onNotification: (notification) => {
 *       if (notification.type === 'notification.delivered') {
 *         showLocalNotification(notification.notification);
 *       }
 *     },
 *   });
 *
 *   return (
 *     <View>
 *       <Text>WS: {state}</Text>
 *     </View>
 *   );
 * }
 * ```
 */
export function useWebSocket(
  options: UseWebSocketOptions = {},
): UseWebSocketReturn {
  const {
    autoConnect = true,
    onMessage,
    onNotification,
    onError,
    ...config
  } = options;

  const { isAuthenticated, isLoading: authLoading } = useAuth();

  const [state, setState] = useState<WebSocketState>("disconnected");
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [lastNotification, setLastNotification] =
    useState<NotificationMessage | null>(null);

  const controllerRef = useRef<WebSocketController | null>(null);
  const callbacksRef = useRef({ onMessage, onNotification, onError });

  // Keep callbacks ref updated
  useEffect(() => {
    callbacksRef.current = { onMessage, onNotification, onError };
  }, [onMessage, onNotification, onError]);

  const connect = useCallback(async () => {
    // Don't connect if already connected or connecting
    if (controllerRef.current?.isConnected()) {
      return;
    }

    // Disconnect existing connection first
    controllerRef.current?.disconnect();

    const callbacks: WebSocketCallbacks = {
      onMessage: (message) => {
        setLastMessage(message);
        callbacksRef.current.onMessage?.(message);
      },
      onNotification: (notification) => {
        setLastNotification(notification);
        callbacksRef.current.onNotification?.(notification);
      },
      onStateChange: setState,
      onError: (error) => {
        callbacksRef.current.onError?.(error);
      },
    };

    try {
      controllerRef.current = await createWebSocketConnection(
        callbacks,
        config,
      );
    } catch (error) {
      console.error("[useWebSocket] Failed to create connection:", error);
    }
  }, [config]);

  const disconnect = useCallback(() => {
    controllerRef.current?.disconnect();
    controllerRef.current = null;
    setState("disconnected");
  }, []);

  // Auto-connect when authenticated
  useEffect(() => {
    if (!autoConnect) return;

    if (!authLoading && isAuthenticated) {
      connect();
    } else if (!isAuthenticated) {
      disconnect();
    }
  }, [autoConnect, authLoading, isAuthenticated, connect, disconnect]);

  // Handle app state changes (reconnect when app comes to foreground)
  useEffect(() => {
    const handleAppStateChange = (nextAppState: AppStateStatus) => {
      if (nextAppState === "active" && isAuthenticated) {
        // Reconnect if we were disconnected while in background
        if (!controllerRef.current?.isConnected()) {
          connect();
        }
      }
    };

    const subscription = AppState.addEventListener(
      "change",
      handleAppStateChange,
    );

    return () => {
      subscription.remove();
    };
  }, [isAuthenticated, connect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      controllerRef.current?.disconnect();
      controllerRef.current = null;
    };
  }, []);

  return {
    state,
    isConnected: state === "connected",
    connect,
    disconnect,
    lastMessage,
    lastNotification,
  };
}
