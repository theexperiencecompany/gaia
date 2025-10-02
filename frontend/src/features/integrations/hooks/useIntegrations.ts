import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import { integrationsApi } from "../api/integrationsApi";
import { Integration, IntegrationStatus } from "../types";

export interface UseIntegrationsReturn {
  integrations: Integration[];
  integrationStatuses: IntegrationStatus[];
  isLoading: boolean;
  error: Error | null;
  connectIntegration: (integrationId: string) => Promise<void>;
  disconnectIntegration: (integrationId: string) => Promise<void>;
  refreshStatus: () => void;
  getIntegrationStatus: (
    integrationId: string,
  ) => IntegrationStatus | undefined;
  getIntegrationsWithStatus: () => Integration[];
  // New helper functions for unified integrations
  getSpecialIntegrations: () => Integration[];
  getRegularIntegrations: () => Integration[];
  isUnifiedIntegrationConnected: (unifiedId: string) => boolean;
}

type UseFetchIntegrationStatusParams = {
  refetchOnMount?: boolean | "always";
};

export const useFetchIntegrationStatus = ({
  refetchOnMount,
}: UseFetchIntegrationStatusParams = {}) => {
  return useQuery({
    queryKey: ["integrations", "status"],
    queryFn: integrationsApi.getIntegrationStatus,
    staleTime: 30 * 60 * 1000, // 30 minutes - cache status for reasonable time
    gcTime: 60 * 60 * 1000, // 1 hour - keep in cache longer than staleTime
    retry: 2,
    refetchOnMount: refetchOnMount,
  });
};

/**
 * Hook for managing integrations and their connection status
 */
export const useIntegrations = (): UseIntegrationsReturn => {
  const queryClient = useQueryClient();

  // Query for integration configuration
  const { data: configData, isLoading: configLoading } = useQuery({
    queryKey: ["integrations", "config"],
    queryFn: integrationsApi.getIntegrationConfig,
    staleTime: 3 * 60 * 60 * 1000, // 3 hours - same as tools cache
    gcTime: 6 * 60 * 60 * 1000, // 6 hours - keep in cache longer
    retry: 2,
    refetchOnWindowFocus: false, // Don't refetch when user focuses window
  });

  // Query for integration status
  const {
    data: statusData,
    isLoading: statusLoading,
    error,
  } = useFetchIntegrationStatus();

  const integrationConfigs = useMemo(
    () => configData?.integrations || [],
    [configData],
  );
  const integrationStatuses = useMemo(
    () => statusData?.integrations || [],
    [statusData],
  );

  // Get status for a specific integration
  const getIntegrationStatus = useCallback(
    (integrationId: string): IntegrationStatus | undefined => {
      return integrationStatuses.find(
        (status) => status.integrationId === integrationId,
      );
    },
    [integrationStatuses],
  );

  // Get integrations with their current status
  const getIntegrationsWithStatus = useCallback((): Integration[] => {
    return integrationConfigs
      .map((integration) => {
        const status = getIntegrationStatus(integration.id);
        return {
          ...integration,
          status: (status?.connected
            ? "connected"
            : "not_connected") as Integration["status"],
        };
      })
      .sort((a, b) => {
        // Sort by display priority (higher first), then by name
        const priorityDiff =
          (b.displayPriority || 0) - (a.displayPriority || 0);
        if (priorityDiff !== 0) return priorityDiff;
        return a.name.localeCompare(b.name);
      });
  }, [integrationConfigs, getIntegrationStatus]);

  // Connect an integration
  const connectIntegration = useCallback(
    async (integrationId: string): Promise<void> => {
      try {
        await integrationsApi.connectIntegration(integrationId);
        // Refresh status after connection attempt
        queryClient.invalidateQueries({ queryKey: ["integrations", "status"] });
      } catch (error) {
        console.error(`Failed to connect ${integrationId}:`, error);
        throw error;
      }
    },
    [queryClient],
  );

  // Disconnect an integration
  const disconnectIntegration = useCallback(
    async (integrationId: string): Promise<void> => {
      try {
        await integrationsApi.disconnectIntegration(integrationId);
        // Refresh status after disconnection
        queryClient.invalidateQueries({ queryKey: ["integrations", "status"] });
      } catch (error) {
        console.error(`Failed to disconnect ${integrationId}:`, error);
        throw error;
      }
    },
    [queryClient],
  );

  // Refresh integration status
  const refreshStatus = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["integrations", "status"] });
  }, [queryClient]);

  // Memoized integrations with status
  const integrationsWithStatus = useMemo(
    () => getIntegrationsWithStatus(),
    [getIntegrationsWithStatus],
  );

  // Get special/unified integrations
  const getSpecialIntegrations = useCallback((): Integration[] => {
    return integrationsWithStatus.filter(
      (integration) => integration.isSpecial,
    );
  }, [integrationsWithStatus]);

  // Get regular integrations (non-special)
  const getRegularIntegrations = useCallback((): Integration[] => {
    return integrationsWithStatus.filter(
      (integration) => !integration.isSpecial,
    );
  }, [integrationsWithStatus]);

  // Check if a unified integration is connected (all its included integrations are connected)
  const isUnifiedIntegrationConnected = useCallback(
    (unifiedId: string): boolean => {
      const unifiedIntegration = integrationsWithStatus.find(
        (integration) => integration.id === unifiedId && integration.isSpecial,
      );

      if (!unifiedIntegration || !unifiedIntegration.includedIntegrations) {
        return false;
      }

      // Check if all included integrations are connected
      return unifiedIntegration.includedIntegrations.every((includedId) => {
        const status = getIntegrationStatus(includedId);
        return status?.connected === true;
      });
    },
    [integrationsWithStatus, getIntegrationStatus],
  );

  return {
    integrations: integrationsWithStatus,
    integrationStatuses,
    isLoading: configLoading || statusLoading,
    error,
    connectIntegration,
    disconnectIntegration,
    refreshStatus,
    getIntegrationStatus,
    getIntegrationsWithStatus,
    getSpecialIntegrations,
    getRegularIntegrations,
    isUnifiedIntegrationConnected,
  };
};
