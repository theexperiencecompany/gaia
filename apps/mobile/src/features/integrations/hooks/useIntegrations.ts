import {
  INTEGRATION_STATE_ORDER,
  integrationConnectionState,
  reconcileIntegrationStatus,
} from "@gaia/shared";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { wsManager } from "@/lib/websocket-client";
import { WS_EVENTS } from "@/lib/websocket-events";
import {
  type ConnectIntegrationResult,
  connectIntegration,
  disconnectIntegration,
  fetchIntegrationStatuses,
  fetchIntegrations,
} from "../api/integrations-api";
import type { Integration } from "../types";

const INTEGRATIONS_QUERY_KEY = ["integrations"] as const;
const INTEGRATION_STATUS_QUERY_KEY = [
  ...INTEGRATIONS_QUERY_KEY,
  "status",
] as const;

const OAUTH_POLL_INTERVAL_MS = 1000;
const OAUTH_POLL_DURATION_MS = 5000;

interface UseIntegrationsResult {
  integrations: Integration[];
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
  connect: (integrationId: string) => Promise<ConnectIntegrationResult>;
  disconnect: (integrationId: string) => Promise<boolean>;
}

function patchStatus(
  integrations: Integration[] | undefined,
  integrationId: string,
  status: Integration["status"],
): Integration[] | undefined {
  if (!integrations) return integrations;
  return integrations.map((item) =>
    item.id === integrationId ? { ...item, status } : item,
  );
}

export function useIntegrations(): UseIntegrationsResult {
  const queryClient = useQueryClient();
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const query = useQuery({
    queryKey: INTEGRATIONS_QUERY_KEY,
    queryFn: fetchIntegrations,
    staleTime: 30 * 1000,
  });
  const statusQuery = useQuery({
    queryKey: INTEGRATION_STATUS_QUERY_KEY,
    queryFn: fetchIntegrationStatuses,
    staleTime: 30 * 1000,
  });

  const integrations = useMemo(() => {
    const statuses = statusQuery.data;
    return (query.data ?? [])
      .map((integration) => ({
        ...integration,
        status: reconcileIntegrationStatus(
          integration.status,
          statuses?.[integration.id],
          integration.managedBy,
          integration.requiresAuth,
        ),
      }))
      .toSorted((a, b) => {
        const priorityA =
          INTEGRATION_STATE_ORDER[integrationConnectionState(a.status)];
        const priorityB =
          INTEGRATION_STATE_ORDER[integrationConnectionState(b.status)];
        if (priorityA !== priorityB) return priorityA - priorityB;
        return a.name.localeCompare(b.name);
      });
  }, [query.data, statusQuery.data]);

  const invalidateIntegrations = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: INTEGRATIONS_QUERY_KEY });
  }, [queryClient]);

  useEffect(() => {
    const handleConnected = () => {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      invalidateIntegrations();
    };

    const handleDisconnected = () => {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      invalidateIntegrations();
    };

    const unsubConnected = wsManager.subscribe(
      WS_EVENTS.INTEGRATION_CONNECTED,
      handleConnected,
    );
    const unsubDisconnected = wsManager.subscribe(
      WS_EVENTS.INTEGRATION_DISCONNECTED,
      handleDisconnected,
    );

    return () => {
      unsubConnected();
      unsubDisconnected();
    };
  }, [invalidateIntegrations]);

  const stopOAuthPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  const startOAuthPolling = useCallback(() => {
    stopOAuthPolling();

    pollTimerRef.current = setInterval(() => {
      invalidateIntegrations();
    }, OAUTH_POLL_INTERVAL_MS);

    pollTimeoutRef.current = setTimeout(() => {
      stopOAuthPolling();
    }, OAUTH_POLL_DURATION_MS);
  }, [stopOAuthPolling, invalidateIntegrations]);

  useEffect(() => {
    return () => {
      stopOAuthPolling();
    };
  }, [stopOAuthPolling]);

  const connect = useCallback(
    async (integrationId: string): Promise<ConnectIntegrationResult> => {
      const previous = queryClient.getQueryData<Integration[]>(
        INTEGRATIONS_QUERY_KEY,
      );

      // Optimistic flip — instant feedback while OAuth resolves.
      queryClient.setQueryData<Integration[] | undefined>(
        INTEGRATIONS_QUERY_KEY,
        (current) => patchStatus(current, integrationId, "connected"),
      );

      const result = await connectIntegration(integrationId);

      if (result.success) {
        void Haptics.notificationAsync(
          Haptics.NotificationFeedbackType.Success,
        );
        // Poll up to 5s in case the WS event lags the OAuth redirect.
        startOAuthPolling();
      } else {
        // Roll back on cancel/failure.
        if (previous) {
          queryClient.setQueryData(INTEGRATIONS_QUERY_KEY, previous);
        }
        if (!result.cancelled) {
          void Haptics.notificationAsync(
            Haptics.NotificationFeedbackType.Warning,
          );
        }
      }

      return result;
    },
    [queryClient, startOAuthPolling],
  );

  const disconnect = useCallback(
    async (integrationId: string): Promise<boolean> => {
      const previous = queryClient.getQueryData<Integration[]>(
        INTEGRATIONS_QUERY_KEY,
      );

      queryClient.setQueryData<Integration[] | undefined>(
        INTEGRATIONS_QUERY_KEY,
        (current) => patchStatus(current, integrationId, "not_connected"),
      );

      const success = await disconnectIntegration(integrationId);

      if (success) {
        void Haptics.notificationAsync(
          Haptics.NotificationFeedbackType.Success,
        );
        invalidateIntegrations();
      } else {
        if (previous) {
          queryClient.setQueryData(INTEGRATIONS_QUERY_KEY, previous);
        }
        void Haptics.notificationAsync(
          Haptics.NotificationFeedbackType.Warning,
        );
      }

      return success;
    },
    [queryClient, invalidateIntegrations],
  );

  return {
    integrations,
    isLoading: query.isLoading,
    error: query.error,
    refetch: invalidateIntegrations,
    connect,
    disconnect,
  };
}
