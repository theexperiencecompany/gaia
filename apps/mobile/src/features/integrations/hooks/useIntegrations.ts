import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useRef } from "react";
import { wsManager } from "@/lib/websocket-client";
import { WS_EVENTS } from "@/lib/websocket-events";
import {
  type ConnectIntegrationResult,
  connectIntegration,
  disconnectIntegration,
  fetchIntegrations,
} from "../api/integrations-api";
import type { Integration } from "../types";

const INTEGRATIONS_QUERY_KEY = ["integrations"] as const;

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

export function useIntegrations(): UseIntegrationsResult {
  const queryClient = useQueryClient();
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const query = useQuery({
    queryKey: INTEGRATIONS_QUERY_KEY,
    queryFn: fetchIntegrations,
    staleTime: 30 * 1000,
  });

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
      const result = await connectIntegration(integrationId);

      if (result.success) {
        // Poll for up to 5s after returning from OAuth browser to catch
        // connection status changes that arrive before the WS event.
        startOAuthPolling();
      }

      return result;
    },
    [startOAuthPolling],
  );

  const disconnect = useCallback(
    async (integrationId: string): Promise<boolean> => {
      const success = await disconnectIntegration(integrationId);
      if (success) {
        invalidateIntegrations();
      }
      return success;
    },
    [invalidateIntegrations],
  );

  return {
    integrations: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: invalidateIntegrations,
    connect,
    disconnect,
  };
}
