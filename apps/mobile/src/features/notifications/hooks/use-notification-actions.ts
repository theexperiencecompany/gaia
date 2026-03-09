import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { inAppNotificationsApi } from "../api";
import type {
  InAppNotification,
  InAppNotificationAction,
  NotificationActionResponse,
} from "../types/inapp-notification-types";

const NOTIFICATIONS_QUERY_PREFIX = ["inapp-notifications"] as const;

interface UseNotificationActionsResult {
  executeNotificationAction: (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ) => Promise<NotificationActionResponse>;
  isActionLoading: (notificationId: string, actionId: string) => boolean;
}

function getActionKey(notificationId: string, actionId: string): string {
  return `${notificationId}:${actionId}`;
}

export function useNotificationActions(): UseNotificationActionsResult {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [loadingActionKeys, setLoadingActionKeys] = useState<Set<string>>(
    new Set(),
  );

  const executeActionMutation = useMutation({
    mutationFn: async ({
      notificationId,
      actionId,
    }: {
      notificationId: string;
      actionId: string;
    }) => inAppNotificationsApi.executeAction(notificationId, actionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: NOTIFICATIONS_QUERY_PREFIX,
      });
    },
  });

  const openRedirect = useCallback(
    async (url: string) => {
      if (url.startsWith("/")) {
        router.push(url as never);
        return;
      }

      await Linking.openURL(url);
    },
    [router],
  );

  const executeNotificationAction = useCallback(
    async (
      notification: InAppNotification,
      action: InAppNotificationAction,
    ): Promise<NotificationActionResponse> => {
      const actionKey = getActionKey(notification.id, action.id);

      setLoadingActionKeys((prev) => {
        const updated = new Set(prev);
        updated.add(actionKey);
        return updated;
      });

      try {
        const response = await executeActionMutation.mutateAsync({
          notificationId: notification.id,
          actionId: action.id,
        });

        const redirectUrl =
          response.data?.redirect_url ?? action.config.redirect?.url;

        if (action.type === "redirect" && redirectUrl) {
          await openRedirect(redirectUrl);
        }

        return response;
      } finally {
        setLoadingActionKeys((prev) => {
          const updated = new Set(prev);
          updated.delete(actionKey);
          return updated;
        });
      }
    },
    [executeActionMutation, openRedirect],
  );

  const isActionLoading = useCallback(
    (notificationId: string, actionId: string) => {
      return loadingActionKeys.has(getActionKey(notificationId, actionId));
    },
    [loadingActionKeys],
  );

  return {
    executeNotificationAction,
    isActionLoading,
  };
}
