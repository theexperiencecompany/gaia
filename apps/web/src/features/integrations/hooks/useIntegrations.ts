import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

import { integrationsApi } from "../api/integrationsApi";
import { integrationKeys, toolKeys } from "../api/queryKeys";
import type {
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
  Integration,
  IntegrationStatus,
} from "../types";

export interface UseIntegrationsReturn {
  // Data
  integrations: Integration[];
  isLoading: boolean;
  error: Error | null;

  // Helpers
  getIntegrationStatus: (
    integrationId: string,
  ) => IntegrationStatus | undefined;

  // Actions
  connectIntegration: (
    integrationId: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  disconnectIntegration: (integrationId: string) => Promise<void>;
  createCustomIntegration: (
    request: CreateCustomIntegrationRequest,
  ) => Promise<CreateCustomIntegrationResponse>;
  deleteCustomIntegration: (integrationId: string) => Promise<void>;
  publishIntegration: (integrationId: string) => Promise<void>;
  unpublishIntegration: (integrationId: string) => Promise<void>;

  // Refresh
  refetch: () => Promise<void>;
}

type UseFetchIntegrationStatusParams = {
  refetchOnMount?: boolean | "always";
};

/**
 * Helper hook to fetch integration status with refetch options.
 * Used by pages that need to force-refresh status on mount.
 */
export const useFetchIntegrationStatus = ({
  refetchOnMount,
}: UseFetchIntegrationStatusParams = {}) => {
  return useQuery({
    queryKey: integrationKeys.status,
    queryFn: integrationsApi.getIntegrationStatus,
    refetchOnMount: refetchOnMount,
  });
};

/**
 * Single hook for managing all integrations (platform + custom).
 * No caching - always fetches fresh data.
 */
export const useIntegrations = (): UseIntegrationsReturn => {
  const queryClient = useQueryClient();
  // The platform catalog (/config) is public, but a user's own integrations
  // and connection status require auth. Gate those on isAuthenticated so public
  // pages (marketplace, use-cases) don't fire 401s for anonymous visitors.
  const { isAuthenticated } = useAuth();

  // Query for platform integration configuration
  const { data: configData, isLoading: configLoading } = useQuery({
    queryKey: integrationKeys.config,
    queryFn: integrationsApi.getIntegrationConfig,
  });

  // Query for user's integrations (includes custom integrations with status)
  const {
    data: userIntegrationsData,
    isLoading: userIntegrationsLoading,
    error,
  } = useQuery({
    queryKey: integrationKeys.user,
    queryFn: integrationsApi.getUserIntegrations,
    staleTime: 0, // Always refetch - user integrations are mutable state
    enabled: isAuthenticated,
  });

  // Query for platform integration status
  const { data: statusData, isLoading: statusLoading } = useQuery({
    queryKey: integrationKeys.status,
    queryFn: integrationsApi.getIntegrationStatus,
    staleTime: 0, // Always refetch - status can change externally (OAuth callbacks)
    enabled: isAuthenticated,
  });

  // Merge platform integrations with user's custom integrations
  const integrations = useMemo(() => {
    const platformConfigs = configData?.integrations || [];
    const userIntegrations = userIntegrationsData?.integrations || [];
    const statuses = statusData?.integrations || [];

    // Build integration list from user's integrations (includes custom)
    const userIntegrationsList: Integration[] = userIntegrations.map((ui) => ({
      id: ui.integrationId,
      name: ui.integration.name,
      description: ui.integration.description,
      category: ui.integration.category as Integration["category"],
      status: ui.status as Integration["status"],
      managedBy: ui.integration.managedBy,
      source: ui.integration.source,
      requiresAuth: ui.integration.requiresAuth,
      authType: ui.integration.authType,
      tools: ui.integration.tools,
      iconUrl: ui.integration.iconUrl ?? undefined,
      isPublic: ui.integration.isPublic ?? undefined,
      createdBy: ui.integration.createdBy ?? undefined,
      creator: ui.integration.creator ?? undefined,
      slug: ui.integration.slug, // Always provided by backend
    }));

    // Get IDs of integrations user already has
    const userIntegrationIds = new Set(
      userIntegrations.map((ui) => ui.integrationId),
    );

    // Build a Map for O(1) status lookups
    const statusMap = new Map(statuses.map((s) => [s.integrationId, s]));

    // Add platform integrations that user hasn't added yet
    const availablePlatformIntegrations: Integration[] = platformConfigs
      .filter((pi) => !userIntegrationIds.has(pi.id))
      .map((pi) => {
        const status = statusMap.get(pi.id);
        return {
          ...pi,
          source: "platform" as const,
          status: status?.connected ? "connected" : ("not_connected" as const),
        };
      });

    // Sort by status: pending (created) first, then connected, then not_connected
    // Within each status group, sort alphabetically by name
    const statusPriority: Record<string, number> = {
      created: 0,
      connected: 1,
      not_connected: 2,
    };

    const allIntegrations = [
      ...userIntegrationsList,
      ...availablePlatformIntegrations,
    ];

    return allIntegrations.toSorted((a, b) => {
      const priorityA = statusPriority[a.status] ?? 3;
      const priorityB = statusPriority[b.status] ?? 3;

      if (priorityA !== priorityB) {
        return priorityA - priorityB;
      }

      return a.name.localeCompare(b.name);
    });
  }, [configData, userIntegrationsData, statusData]);

  // Read the latest integrations inside callbacks without making the callbacks
  // depend on the array — otherwise every refetch changes their identity and
  // churns consumers (e.g. the sidebar content rebuilt on every poll tick).
  const integrationsRef = useRef(integrations);
  integrationsRef.current = integrations;

  // Get status for a specific integration
  const getIntegrationStatus = useCallback(
    (integrationId: string): IntegrationStatus | undefined => {
      return statusData?.integrations.find(
        (s) => s.integrationId.toLowerCase() === integrationId.toLowerCase(),
      );
    },
    [statusData],
  );

  // Connect integration
  const connectIntegration = useCallback(
    async (
      integrationId: string,
    ): Promise<{ status: string; name?: string; toolsCount?: number }> => {
      const integration = integrationsRef.current.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      const integrationName = integration?.name || "Integration";

      const toastId = toast.loading(`Connecting to ${integrationName}...`);

      try {
        const result = await integrationsApi.connectIntegration(integrationId);

        if (result.status === "connected") {
          trackEvent(ANALYTICS_EVENTS.INTEGRATION_CONNECTED, {
            integration: integrationId,
            source: "integration_settings",
          });
          toast.success(`Connected to ${result.name}`, { id: toastId });
          // Invalidate (not awaited refetch) so the button/sidebar update in the
          // background instead of blocking on two integration/tools GETs.
          queryClient.invalidateQueries({ queryKey: integrationKeys.all });
          queryClient.invalidateQueries({ queryKey: toolKeys.available });
        } else if (result.status === "redirecting") {
          // OAuth redirect in progress - dismiss toast, browser will navigate
          toast.dismiss(toastId);
        } else {
          // Handle unexpected status (e.g., failed, pending, etc.)
          toast.error(`Connection failed: ${result.status}`, { id: toastId });
        }

        return result;
      } catch (error) {
        toast.error(
          `Failed to connect: ${error instanceof Error ? error.message : "Unknown error"}`,
          { id: toastId },
        );
        trackEvent(ANALYTICS_EVENTS.INTEGRATION_ERROR, {
          integration: integrationId,
          error: error instanceof Error ? error.message : "Unknown error",
        });
        throw error;
      }
    },
    [queryClient],
  );

  // Disconnect integration
  const disconnectIntegration = useCallback(
    async (integrationId: string): Promise<void> => {
      try {
        await integrationsApi.disconnectIntegration(integrationId);
        trackEvent(ANALYTICS_EVENTS.INTEGRATION_DISCONNECTED, {
          integration: integrationId,
        });
        toast.success("Integration disconnected");
        // Invalidate (not refetch) so the UI updates in the background while
        // the modal closes immediately. Awaiting refetch here blocked the
        // sidebar for the duration of three integration GETs.
        queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      } catch (error) {
        toast.error(
          `Failed to disconnect: ${error instanceof Error ? error.message : "Unknown error"}`,
        );
        trackEvent(ANALYTICS_EVENTS.INTEGRATION_ERROR, {
          integration: integrationId,
          error: error instanceof Error ? error.message : "Unknown error",
        });
        throw error;
      }
    },
    [queryClient],
  );

  // Create custom integration mutation
  // Backend now auto-connects, so we need to refetch both integrations AND tools
  const createMutation = useMutation({
    mutationFn: integrationsApi.createCustomIntegration,
    onSuccess: () => {
      // Refetch integrations to update connection status
      queryClient.refetchQueries({ queryKey: integrationKeys.all });
      // Refetch tools since backend auto-connects and discovers tools
      queryClient.refetchQueries({ queryKey: toolKeys.available });
    },
  });

  const createCustomIntegration = useCallback(
    async (request: CreateCustomIntegrationRequest) => {
      return await createMutation.mutateAsync(request);
    },
    [createMutation],
  );

  // Delete custom integration mutation
  const deleteMutation = useMutation({
    mutationFn: integrationsApi.deleteCustomIntegration,
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: integrationKeys.all });
    },
  });

  const deleteCustomIntegration = useCallback(
    async (integrationId: string) => {
      await deleteMutation.mutateAsync(integrationId);
    },
    [deleteMutation],
  );

  // Publish custom integration
  const publishIntegration = useCallback(
    async (integrationId: string): Promise<void> => {
      const integration = integrationsRef.current.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      const integrationName = integration?.name || integrationId;

      const toastId = toast.loading(`Publishing ${integrationName}...`);

      try {
        const { publicUrl } =
          await integrationsApi.publishIntegration(integrationId);
        toast.success(`${integrationName} published to community`, {
          id: toastId,
        });

        if (typeof window !== "undefined") {
          // Navigate to the published integration's marketplace page. The full
          // reload refetches data, so an explicit refetch here would be wasted.
          window.location.href = publicUrl;
        }
      } catch (error) {
        toast.error(
          `Failed to publish: ${error instanceof Error ? error.message : "Unknown error"}`,
          { id: toastId },
        );
        throw error;
      }
    },
    [],
  );

  // Unpublish custom integration
  const unpublishIntegration = useCallback(
    async (integrationId: string): Promise<void> => {
      const integration = integrationsRef.current.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      const integrationName = integration?.name || integrationId;

      const toastId = toast.loading(`Unpublishing ${integrationName}...`);

      try {
        await integrationsApi.unpublishIntegration(integrationId);
        toast.success(`${integrationName} unpublished`, { id: toastId });
        await queryClient.refetchQueries({ queryKey: integrationKeys.all });
      } catch (error) {
        toast.error(
          `Failed to unpublish: ${error instanceof Error ? error.message : "Unknown error"}`,
          { id: toastId },
        );
        throw error;
      }
    },
    [queryClient],
  );

  // Simple refetch all
  const refetch = useCallback(async () => {
    await queryClient.refetchQueries({ queryKey: integrationKeys.all });
  }, [queryClient]);

  return {
    integrations,
    isLoading: configLoading || userIntegrationsLoading || statusLoading,
    error: error as Error | null,
    getIntegrationStatus,
    connectIntegration,
    disconnectIntegration,
    createCustomIntegration,
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
    refetch,
  };
};
