import {
  type UseQueryResult,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";
import { wsManager } from "@/lib/websocket-client";
import { WS_EVENTS } from "@/lib/websocket-events";
import { inAppNotificationsApi } from "../api";
import {
  type InAppNotification,
  InAppNotificationStatus,
  type InAppNotificationsListResponse,
} from "../types/inapp-notification-types";

const notificationsKeys = {
  all: ["inapp-notifications"] as const,
  unread: () => [...notificationsKeys.all, "unread"] as const,
  list: () => [...notificationsKeys.all, "list"] as const,
  archived: () => [...notificationsKeys.all, "archived"] as const,
};

type RawNotification = Record<string, unknown>;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function getString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function normalizeNotification(raw: RawNotification): InAppNotification {
  const originalRequest = asRecord(raw.original_request);
  const contentFromRoot = asRecord(raw.content);
  const contentFromRequest = asRecord(originalRequest?.content);
  const content = contentFromRoot ?? contentFromRequest ?? {};

  const title = getString(content.title) ?? "Notification";
  const body = getString(content.body) ?? "";

  const actions = Array.isArray(content.actions)
    ? content.actions.filter((entry) => !!asRecord(entry))
    : undefined;

  const status = getString(raw.status) ?? InAppNotificationStatus.DELIVERED;

  return {
    id: getString(raw.id) ?? `unknown-${Date.now()}`,
    status: status as InAppNotificationStatus,
    source:
      getString(raw.source) ?? getString(originalRequest?.source) ?? undefined,
    type: getString(raw.type) ?? getString(originalRequest?.type) ?? undefined,
    created_at:
      getString(raw.created_at) ??
      getString(raw.delivered_at) ??
      new Date().toISOString(),
    read_at: getString(raw.read_at),
    content: {
      title,
      body,
      actions: actions as InAppNotification["content"]["actions"],
    },
  };
}

function normalizeListResponse(
  response: InAppNotificationsListResponse,
): InAppNotificationsListResponse {
  const normalizedNotifications = (response.notifications ?? []).map((entry) =>
    normalizeNotification(entry as unknown as RawNotification),
  );

  return {
    notifications: normalizedNotifications,
    total: response.total ?? normalizedNotifications.length,
    limit: response.limit ?? normalizedNotifications.length,
    offset: response.offset ?? 0,
  };
}

interface UseInappNotificationsResult {
  unreadNotifications: InAppNotification[];
  allNotifications: InAppNotification[];
  archivedNotifications: InAppNotification[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  markAsRead: (notificationId: string) => Promise<void>;
  markAllAsRead: (notificationIds: string[]) => Promise<void>;
  archiveNotification: (notificationId: string) => Promise<void>;
  deleteNotification: (notificationId: string) => Promise<void>;
  bulkMarkRead: (notificationIds: string[]) => Promise<void>;
  bulkArchive: (notificationIds: string[]) => Promise<void>;
  bulkDelete: (notificationIds: string[]) => Promise<void>;
  isMarkingAsRead: boolean;
  isMarkingAllAsRead: boolean;
  isArchiving: boolean;
  isDeleting: boolean;
}

function getErrorMessage(
  unreadQuery: UseQueryResult<InAppNotificationsListResponse, Error>,
  allQuery: UseQueryResult<InAppNotificationsListResponse, Error>,
): string | null {
  return unreadQuery.error?.message ?? allQuery.error?.message ?? null;
}

export function useInappNotifications(): UseInappNotificationsResult {
  const queryClient = useQueryClient();

  useEffect(() => {
    const invalidateAll = () => {
      void queryClient.invalidateQueries({
        queryKey: notificationsKeys.all,
      });
    };

    const unsubDelivered = wsManager.subscribe(
      WS_EVENTS.NOTIFICATION_DELIVERED,
      invalidateAll,
    );
    const unsubRead = wsManager.subscribe(
      WS_EVENTS.NOTIFICATION_READ,
      invalidateAll,
    );
    const unsubUpdated = wsManager.subscribe(
      WS_EVENTS.NOTIFICATION_UPDATED,
      invalidateAll,
    );

    return () => {
      unsubDelivered();
      unsubRead();
      unsubUpdated();
    };
  }, [queryClient]);

  const unreadQuery = useQuery({
    queryKey: notificationsKeys.unread(),
    queryFn: async () => {
      const response = await inAppNotificationsApi.getNotifications({
        status: InAppNotificationStatus.DELIVERED,
        limit: 100,
      });

      return normalizeListResponse(response);
    },
  });

  const allQuery = useQuery({
    queryKey: notificationsKeys.list(),
    queryFn: async () => {
      const response = await inAppNotificationsApi.getNotifications({
        limit: 100,
      });

      return normalizeListResponse(response);
    },
  });

  const archivedQuery = useQuery({
    queryKey: notificationsKeys.archived(),
    queryFn: async () => {
      const response = await inAppNotificationsApi.getNotifications({
        status: InAppNotificationStatus.ARCHIVED,
        limit: 100,
      });

      return normalizeListResponse(response);
    },
  });

  const markAsReadMutation = useMutation({
    mutationFn: async (notificationId: string) => {
      await inAppNotificationsApi.markAsRead(notificationId);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: notificationsKeys.unread() }),
        queryClient.invalidateQueries({ queryKey: notificationsKeys.list() }),
      ]);
    },
  });

  const bulkMarkAsReadMutation = useMutation({
    mutationFn: async (notificationIds: string[]) => {
      if (notificationIds.length === 0) {
        return;
      }

      await inAppNotificationsApi.bulkMarkAsRead(notificationIds);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: notificationsKeys.unread() }),
        queryClient.invalidateQueries({ queryKey: notificationsKeys.list() }),
      ]);
    },
  });

  const archiveMutation = useMutation({
    mutationFn: async (notificationId: string) => {
      await inAppNotificationsApi.archiveNotification(notificationId);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: notificationsKeys.unread() }),
        queryClient.invalidateQueries({ queryKey: notificationsKeys.list() }),
        queryClient.invalidateQueries({
          queryKey: notificationsKeys.archived(),
        }),
      ]);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (notificationId: string) => {
      await inAppNotificationsApi.deleteNotification(notificationId);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: notificationsKeys.unread() }),
        queryClient.invalidateQueries({ queryKey: notificationsKeys.list() }),
        queryClient.invalidateQueries({
          queryKey: notificationsKeys.archived(),
        }),
      ]);
    },
  });

  const bulkArchiveMutation = useMutation({
    mutationFn: async (notificationIds: string[]) => {
      if (notificationIds.length === 0) return;
      await inAppNotificationsApi.bulkArchive(notificationIds);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: notificationsKeys.unread() }),
        queryClient.invalidateQueries({ queryKey: notificationsKeys.list() }),
        queryClient.invalidateQueries({
          queryKey: notificationsKeys.archived(),
        }),
      ]);
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: async (notificationIds: string[]) => {
      if (notificationIds.length === 0) return;
      await inAppNotificationsApi.bulkDelete(notificationIds);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: notificationsKeys.unread() }),
        queryClient.invalidateQueries({ queryKey: notificationsKeys.list() }),
        queryClient.invalidateQueries({
          queryKey: notificationsKeys.archived(),
        }),
      ]);
    },
  });

  const bulkMarkReadMutation = useMutation({
    mutationFn: async (notificationIds: string[]) => {
      if (notificationIds.length === 0) return;
      await inAppNotificationsApi.bulkMarkRead(notificationIds);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: notificationsKeys.unread() }),
        queryClient.invalidateQueries({ queryKey: notificationsKeys.list() }),
      ]);
    },
  });

  return {
    unreadNotifications: unreadQuery.data?.notifications ?? [],
    allNotifications: allQuery.data?.notifications ?? [],
    archivedNotifications: archivedQuery.data?.notifications ?? [],
    isLoading:
      unreadQuery.isLoading || allQuery.isLoading || archivedQuery.isLoading,
    isRefreshing:
      unreadQuery.isRefetching ||
      allQuery.isRefetching ||
      archivedQuery.isRefetching,
    error: getErrorMessage(unreadQuery, allQuery),
    refetch: async () => {
      await Promise.all([
        unreadQuery.refetch(),
        allQuery.refetch(),
        archivedQuery.refetch(),
      ]);
    },
    markAsRead: async (notificationId: string) => {
      await markAsReadMutation.mutateAsync(notificationId);
    },
    markAllAsRead: async (notificationIds: string[]) => {
      await bulkMarkAsReadMutation.mutateAsync(notificationIds);
    },
    archiveNotification: async (notificationId: string) => {
      await archiveMutation.mutateAsync(notificationId);
    },
    deleteNotification: async (notificationId: string) => {
      await deleteMutation.mutateAsync(notificationId);
    },
    bulkMarkRead: async (notificationIds: string[]) => {
      await bulkMarkReadMutation.mutateAsync(notificationIds);
    },
    bulkArchive: async (notificationIds: string[]) => {
      await bulkArchiveMutation.mutateAsync(notificationIds);
    },
    bulkDelete: async (notificationIds: string[]) => {
      await bulkDeleteMutation.mutateAsync(notificationIds);
    },
    isMarkingAsRead: markAsReadMutation.isPending,
    isMarkingAllAsRead: bulkMarkAsReadMutation.isPending,
    isArchiving: archiveMutation.isPending,
    isDeleting: deleteMutation.isPending,
  };
}
