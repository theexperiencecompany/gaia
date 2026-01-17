import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { toast } from "sonner";

import { integrationsApi } from "../api/integrationsApi";
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
  refetch: () => void;
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
    queryKey: ["integrations", "status"],
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

  // Query for platform integration configuration
  const { data: configData, isLoading: configLoading } = useQuery({
    queryKey: ["integrations", "config"],
    queryFn: integrationsApi.getIntegrationConfig,
  });

  // Query for user's integrations (includes custom integrations with status)
  const {
    data: userIntegrationsData,
    isLoading: userIntegrationsLoading,
    error,
  } = useQuery({
    queryKey: ["integrations", "user"],
    queryFn: integrationsApi.getUserIntegrations,
  });

  // Query for platform integration status
  const { data: statusData, isLoading: statusLoading } = useQuery({
    queryKey: ["integrations", "status"],
    queryFn: integrationsApi.getIntegrationStatus,
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
    }));

    // Get IDs of integrations user already has
    const userIntegrationIds = new Set(
      userIntegrations.map((ui) => ui.integrationId),
    );

    // Add platform integrations that user hasn't added yet
    const availablePlatformIntegrations: Integration[] = platformConfigs
      .filter((pi) => !userIntegrationIds.has(pi.id))
      .map((pi) => {
        const status = statuses.find((s) => s.integrationId === pi.id);
        return {
          ...pi,
          source: "platform" as const,
          status: status?.connected ? "connected" : ("not_connected" as const),
        };
      });

    return [...userIntegrationsList, ...availablePlatformIntegrations];
  }, [configData, userIntegrationsData, statusData]);

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
    ): Promise<{ status: string; toolsCount?: number }> => {
      const integration = integrations.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      const integrationName = integration?.name || integrationId;

      const toastId = toast.loading(`Connecting to ${integrationName}...`);

      try {
        const result = await integrationsApi.connectIntegration(integrationId);

        if (result.status === "connected") {
          toast.success(`Connected to ${integrationName}`, { id: toastId });
          // Refetch all data
          await Promise.all([
            queryClient.refetchQueries({ queryKey: ["integrations"] }),
            queryClient.refetchQueries({ queryKey: ["tools", "available"] }),
          ]);
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
        throw error;
      }
    },
    [queryClient, integrations],
  );

  // Disconnect integration
  const disconnectIntegration = useCallback(
    async (integrationId: string): Promise<void> => {
      try {
        await integrationsApi.disconnectIntegration(integrationId);
        toast.success("Integration disconnected");
        // Refetch all data
        await queryClient.refetchQueries({ queryKey: ["integrations"] });
      } catch (error) {
        toast.error(
          `Failed to disconnect: ${error instanceof Error ? error.message : "Unknown error"}`,
        );
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
      queryClient.refetchQueries({ queryKey: ["integrations"] });
      // Refetch tools since backend auto-connects and discovers tools
      queryClient.refetchQueries({ queryKey: ["tools", "available"] });
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
      queryClient.refetchQueries({ queryKey: ["integrations"] });
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
      const integration = integrations.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      const integrationName = integration?.name || integrationId;

      const toastId = toast.loading(`Publishing ${integrationName}...`);

      try {
        await integrationsApi.publishIntegration(integrationId);
        toast.success(`${integrationName} published to community`, {
          id: toastId,
        });
        await queryClient.refetchQueries({ queryKey: ["integrations"] });
      } catch (error) {
        toast.error(
          `Failed to publish: ${error instanceof Error ? error.message : "Unknown error"}`,
          { id: toastId },
        );
        throw error;
      }
    },
    [queryClient, integrations],
  );

  // Unpublish custom integration
  const unpublishIntegration = useCallback(
    async (integrationId: string): Promise<void> => {
      const integration = integrations.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      const integrationName = integration?.name || integrationId;

      const toastId = toast.loading(`Unpublishing ${integrationName}...`);

      try {
        await integrationsApi.unpublishIntegration(integrationId);
        toast.success(`${integrationName} unpublished`, { id: toastId });
        await queryClient.refetchQueries({ queryKey: ["integrations"] });
      } catch (error) {
        toast.error(
          `Failed to unpublish: ${error instanceof Error ? error.message : "Unknown error"}`,
          { id: toastId },
        );
        throw error;
      }
    },
    [queryClient, integrations],
  );

  // Simple refetch all
  const refetch = useCallback(() => {
    queryClient.refetchQueries({ queryKey: ["integrations"] });
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
