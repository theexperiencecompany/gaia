import { useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";

import { useUser } from "@/features/auth/hooks/useUser";
import {
  NotificationRecord,
  NotificationUpdate,
  UseNotificationWebSocketOptions,
} from "@/types/features/notificationTypes";

interface WebSocketMessage {
  type:
    | "notification.delivered"
    | "notification.updated"
    | "notification.read"
    | "notification.reactivated"
    | "ping"
    | "error";
  notification?: NotificationRecord;
  notification_id?: string;
  updates?: NotificationUpdate;
  message?: string;
}

export function useNotificationWebSocket(
  options: UseNotificationWebSocketOptions = {},
) {
  const user = useUser();
  const isAuthenticated = !!user?.email;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;
  const baseReconnectDelay = 1000; // 1 second

  const connect = useCallback(() => {
    // Don't connect if user is not authenticated
    if (!isAuthenticated) return;

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      // Get WebSocket URL from backend API base URL
      const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
      if (!apiBaseUrl) {
        throw new Error(
          "NEXT_PUBLIC_API_BASE_URL environment variable not set",
        );
      }

      // Convert HTTP/HTTPS to WS/WSS protocol
      const wsUrl =
        apiBaseUrl.replace("http://", "ws://").replace("https://", "wss://") +
        "ws/connect";

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("WebSocket connected for notifications");
        reconnectAttempts.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);

          switch (message.type) {
            case "notification.delivered":
              if (message.notification && options.onNotification) {
                options.onNotification(message.notification);

                // Skip showing toast for test notifications to avoid duplicates
                const isTestNotification =
                  message.notification.metadata?.test === true;

                if (!isTestNotification) {
                  // Check if notification data structure is complete before showing toast
                  if (message.notification.content?.title) {
                    toast.info(message.notification.content.title, {
                      description:
                        message.notification.content.body ||
                        "New notification received",
                      dismissible: true,
                      duration: 10000, // Show for 5 seconds
                    });
                  } else {
                    // Fallback if content is missing
                    toast.info("New notification", {
                      description: "You have received a new notification",
                    });
                  }
                }
              }
              break;

            case "notification.updated":
              if (message.notification && options.onUpdate) {
                options.onUpdate(message.notification);
              }
              break;

            case "ping":
              // Respond to ping to keep connection alive
              ws.send(JSON.stringify({ type: "pong" }));
              break;

            case "error":
              console.error("WebSocket error message:", message.message);
              if (options.onError) {
                options.onError(
                  new Error(message.message || "WebSocket error"),
                );
              }
              break;

            default:
              console.warn("Unknown WebSocket message type:", message.type);
          }
        } catch (error) {
          console.error("Error parsing WebSocket message:", error);
          if (options.onError) {
            options.onError(error as Error);
          }
        }
      };

      ws.onclose = (event) => {
        console.log("WebSocket disconnected:", event.code, event.reason);
        wsRef.current = null;

        // Don't reconnect if close was intentional
        if (event.code === 1000) {
          return;
        }

        // Attempt reconnection with exponential backoff
        if (reconnectAttempts.current < maxReconnectAttempts) {
          const delay =
            baseReconnectDelay * Math.pow(2, reconnectAttempts.current);
          reconnectAttempts.current++;

          console.log(
            `Attempting to reconnect in ${delay}ms (attempt ${reconnectAttempts.current})`,
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          console.error("Max reconnection attempts reached");
          if (options.onError) {
            options.onError(
              new Error("Failed to reconnect to notification WebSocket"),
            );
          }
        }
      };

      ws.onerror = (error) => {
        console.error("WebSocket connection error:", error);
        if (options.onError) {
          options.onError(new Error("WebSocket connection failed"));
        }
      };
    } catch (error) {
      console.error("Error creating WebSocket connection:", error);
      if (options.onError) {
        options.onError(error as Error);
      }
    }
  }, [options, isAuthenticated]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, "Intentional disconnect");
      wsRef.current = null;
    }

    reconnectAttempts.current = 0;
  }, []);

  // Connect on mount only if authenticated
  useEffect(() => {
    if (isAuthenticated) {
      connect();
    }
    return disconnect;
  }, [connect, disconnect, isAuthenticated]);

  // Handle page visibility changes to reconnect when page becomes visible
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        // Reconnect if connection is lost
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          connect();
        }
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [connect]);

  return {
    connect,
    disconnect,
    isConnected: wsRef.current?.readyState === WebSocket.OPEN,
  };
}
