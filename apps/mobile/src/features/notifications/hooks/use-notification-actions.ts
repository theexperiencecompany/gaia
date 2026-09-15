import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import { type Dispatch, type SetStateAction, useState } from "react";
import { inAppNotificationsApi } from "@/features/notifications/api/inapp-notifications-api";
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

/**
 * Marks `key` loading for the duration of `run`, resolve or throw. A plain
 * function, not part of the hook: React Compiler cannot compile `finally`.
 */
async function withLoadingKey<T>(
  setKeys: Dispatch<SetStateAction<Set<string>>>,
  key: string,
  run: () => Promise<T>,
): Promise<T> {
  setKeys((prev) => new Set(prev).add(key));
  try {
    return await run();
  } finally {
    setKeys((prev) => {
      const updated = new Set(prev);
      updated.delete(key);
      return updated;
    });
  }
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

  const openRedirect = async (url: string) => {
    if (url.startsWith("/")) {
      router.push(url as never);
      return;
    }

    await Linking.openURL(url);
  };

  const executeNotificationAction = async (
    notification: InAppNotification,
    action: InAppNotificationAction,
  ): Promise<NotificationActionResponse> => {
    const actionKey = getActionKey(notification.id, action.id);

    return withLoadingKey(setLoadingActionKeys, actionKey, async () => {
      const response = await executeActionMutation.mutateAsync({
        notificationId: notification.id,
        actionId: action.id,
      });

      const redirectUrl =
        response.data?.redirect_url ?? action.config?.redirect?.url;

      if (action.type === "redirect" && redirectUrl) {
        await openRedirect(redirectUrl);
      }

      return response;
    });
  };

  const isActionLoading = (notificationId: string, actionId: string) => {
    return loadingActionKeys.has(getActionKey(notificationId, actionId));
  };

  return {
    executeNotificationAction,
    isActionLoading,
  };
}
