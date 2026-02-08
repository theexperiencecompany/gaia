import { useCallback, useEffect } from "react";
import { toast } from "sonner";

import { useUser } from "@/features/auth/hooks/useUser";
import { wsManager } from "@/lib/websocket";
import { batchSyncConversations } from "@/services/syncService";
import { useNotificationStore } from "@/stores/notificationStore";
import type {
  NotificationRecord,
  NotificationUpdate,
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

export function useNotificationWebSocket() {
  const user = useUser();
  const isAuthenticated = !!user?.email;
  const { addNotification, updateNotification } = useNotificationStore();

  const handleMessage = useCallback(
    (msg: unknown) => {
      const message = msg as WebSocketMessage;
      switch (message.type) {
        case "notification.delivered":
          if (message.notification) {
            addNotification(message.notification);

            const isTestNotification =
              message.notification.metadata?.test === true;

            if (!isTestNotification) {
              if (message.notification.content?.title) {
                toast.info(message.notification.content.title, {
                  description:
                    message.notification.content.body ||
                    "New notification received",
                  dismissible: true,
                  duration: 10000,
                });
              } else {
                toast.info("New notification", {
                  description: "You have received a new notification",
                });
              }
            }

            // Sync chats when a workflow completion notification arrives
            if (message.notification.metadata?.conversation_id) {
              batchSyncConversations();
            }
          }
          break;

        case "notification.updated":
          if (message.notification) {
            updateNotification(message.notification);
          }
          break;

        case "error":
          console.error("WebSocket error message:", message.message);
          break;

        default:
          console.warn("Unknown notification message type:", message.type);
      }
    },
    [addNotification, updateNotification],
  );

  const handleError = useCallback((error: Error) => {
    console.error("WebSocket connection error:", error);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;

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
