import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { notificationKeys } from "@/features/notification/api/queryKeys";
import { toast } from "@/lib/toast";
import { isSafeInternalPath } from "@/lib/url-safety";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { batchSyncConversations } from "@/services/syncService";
import type {
  NotificationAction,
  NotificationView,
} from "@/types/features/notificationTypes";
import {
  ActionType,
  NotificationType,
} from "@/types/features/notificationTypes";

/** Every notification push the server sends; each one means the list changed. */
const NOTIFICATION_EVENTS = [
  "notification.delivered",
  "notification.updated",
  "notification.read",
  "notification.all_read",
] as const;

interface WebSocketMessage {
  type: (typeof NOTIFICATION_EVENTS)[number];
  notification?: NotificationView;
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
    batchSyncConversations({ background: true });
  }
}

export function useNotificationWebSocket() {
  const user = useCurrentUser();
  const isAuthenticated = !!user?.email;
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
      // The server's list is the truth: a push only says it changed.
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
      if (message.type === "notification.delivered" && message.notification) {
        const isOnboarding =
          pathnameRef.current?.includes("/onboarding") ?? false;
        handleDeliveredNotification(message.notification, router, isOnboarding);
      }
    },
    [queryClient, router],
  );

  const handleError = useCallback((error: Error) => {
    console.error("WebSocket connection error:", error);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;

    for (const event of NOTIFICATION_EVENTS) wsManager.on(event, handleMessage);
    wsManager.onError(handleError);

    return () => {
      for (const event of NOTIFICATION_EVENTS)
        wsManager.off(event, handleMessage);
      wsManager.offError(handleError);
    };
  }, [isAuthenticated, handleMessage, handleError]);

  return {
    isConnected: wsManager.isConnected,
  };
}
