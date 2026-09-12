import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import {
  prependNotification,
  upsertNotification,
} from "@/features/notification/api/notificationCache";
import { toast } from "@/lib/toast";
import { isSafeInternalPath } from "@/lib/url-safety";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { batchSyncConversations } from "@/services/syncService";
import type {
  NotificationAction,
  NotificationUpdate,
  NotificationView,
} from "@/types/features/notificationTypes";
import {
  ActionType,
  NotificationType,
} from "@/types/features/notificationTypes";

interface WebSocketMessage {
  type:
    | "notification.delivered"
    | "notification.updated"
    | "notification.read"
    | "notification.reactivated"
    | "ping"
    | "error";
  notification?: NotificationView;
  notification_id?: string;
  updates?: NotificationUpdate;
  message?: string;
}

type AppRouter = ReturnType<typeof useRouter>;

function resolveToastFn(notifType: NotificationType) {
  switch (notifType) {
    case NotificationType.ERROR:
      return toast.error;
    case NotificationType.SUCCESS:
      return toast.success;
    case NotificationType.WARNING:
      return toast.warning;
    default:
      return toast.info;
  }
}

function buildRedirectAction(
  redirectAction: NotificationAction | undefined,
  router: AppRouter,
) {
  if (!redirectAction) return undefined;
  return {
    label: redirectAction.label,
    onClick: () => {
      const url = redirectAction.config?.redirect?.url;
      // Backend/LLM-driven payload — only navigate to safe
      // internal relative paths to prevent open redirects.
      if (url && isSafeInternalPath(url)) {
        router.push(url);
      } else if (url) {
        console.warn("[NotificationWS] Blocked unsafe redirect url:", url);
      }
    },
  };
}

function showDeliveredToast(notification: NotificationView, router: AppRouter) {
  if (!notification.content?.title) {
    toast.info("New notification", {
      description: "You have received a new notification",
    });
    return;
  }

  const actions = notification.content.actions ?? [];
  const redirectAction = actions.find((a) => a.type === ActionType.REDIRECT);
  const notifType = notification.type as NotificationType;
  const toastFn = resolveToastFn(notifType);

  toastFn(notification.content.title, {
    description: notification.content.body || "New notification received",
    duration: notifType === NotificationType.ERROR ? 15000 : 10000,
    action: buildRedirectAction(redirectAction, router),
  });
}

function handleDeliveredNotification(
  notification: NotificationView,
  router: AppRouter,
  isOnboarding: boolean,
) {
  const isTestNotification = notification.metadata?.test === true;
  if (!isTestNotification && !isOnboarding) {
    showDeliveredToast(notification, router);
  }

  // Sync chats when a workflow completion notification arrives
  if (notification.metadata?.conversation_id) {
    console.debug(
      "[NotificationWS] Notification has conversation_id, triggering sync",
      notification.metadata.conversation_id,
    );
    batchSyncConversations();
  }
}

export function useNotificationWebSocket() {
  const user = useCurrentUser();
  const isAuthenticated = !!user?.email;
  // Live pushes are written straight into the query cache the lists read —
  // same keys, no parallel store to drift out of sync.
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  // Ref keeps handleMessage stable so the ws listener isn't re-registered.
  const pathnameRef = useRef(pathname);
  useEffect(() => {
    pathnameRef.current = pathname;
  });

  const handleMessage = useCallback(
    (msg: unknown) => {
      const message = msg as WebSocketMessage;
      switch (message.type) {
        case "notification.delivered":
          if (message.notification) {
            prependNotification(queryClient, message.notification);
            const isOnboarding =
              pathnameRef.current?.includes("/onboarding") ?? false;
            handleDeliveredNotification(
              message.notification,
              router,
              isOnboarding,
            );
          }
          break;

        case "notification.updated":
          if (message.notification) {
            upsertNotification(queryClient, message.notification);
          }
          break;

        case "error":
          console.error("WebSocket error message:", message.message);
          break;

        default:
          console.warn("Unknown notification message type:", message.type);
      }
    },
    [queryClient, router],
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
