import { useCallback, useEffect } from "react";
import { toast } from "sonner";

import { useUser } from "@/features/auth/hooks/useUser";
import {
  NotificationRecord,
  NotificationUpdate,
  UseNotificationWebSocketOptions,
} from "@/types/features/notificationTypes";
import { wsManager } from "@/lib/websocket";

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

  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
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
                  duration: 10000,
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

        case "error":
          console.error("WebSocket error message:", message.message);
          if (options.onError) {
            options.onError(new Error(message.message || "WebSocket error"));
          }
          break;

        default:
          console.warn("Unknown notification message type:", message.type);
      }
    },
    [options],
  );

  const handleError = useCallback(
    (error: Error) => {
      if (options.onError) {
        options.onError(error);
      }
    },
    [options],
  );

  // Subscribe to notification messages
  useEffect(() => {
    if (!isAuthenticated) return;

    // Listen for all notification.* messages
    wsManager.on("notification.delivered", handleMessage);
    wsManager.on("notification.updated", handleMessage);
    wsManager.on("error", handleMessage);
    wsManager.onError(handleError);

    return () => {
      wsManager.off("notification.delivered", handleMessage);
      wsManager.off("notification.updated", handleMessage);
      wsManager.off("error", handleMessage);
      wsManager.offError(handleError);
    };
  }, [isAuthenticated, handleMessage, handleError]);

  return {
    isConnected: wsManager.isConnected,
  };
}
