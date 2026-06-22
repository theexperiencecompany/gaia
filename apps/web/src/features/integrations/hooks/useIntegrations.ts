import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

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
  refetch: () => Promise<void>;
}

/**
 * Single hook for managing all integrations (platform + custom).
 * Backed by GET /integrations/me — the full catalog personalized for the user,
 * each entry carrying its connection status.
 */
export const useIntegrations = (): UseIntegrationsReturn => {
  const queryClient = useQueryClient();
  // /integrations/me is personalized and requires auth, so gate it on
  // isAuthenticated — public pages (marketplace, use-cases) must not fire 401s
  // for anonymous visitors.
  const { isAuthenticated } = useAuth();

  const {
    data: myIntegrationsData,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["integrations", "me"],
    queryFn: integrationsApi.getMyIntegrations,
    staleTime: 0, // Always refetch - status changes externally (OAuth callbacks)
    enabled: isAuthenticated,
  });

  // Map the personalized catalog into the Integration shape the app consumes,
  // sorted by status (created → connected → not_connected) then name.
  const integrations = useMemo((): Integration[] => {
    const items = myIntegrationsData?.integrations ?? [];

    const mapped: Integration[] = items.map((item) => ({
      id: item.id,
      name: item.name,
      description: item.description,
      category: item.category as Integration["category"],
      status: item.status,
      managedBy: item.managedBy,
      source: item.source,
      requiresAuth: item.requiresAuth,
      authType: item.authType ?? undefined,
      isFeatured: item.isFeatured,
      displayPriority: item.displayPriority,
      available: item.available,
      toolCount: item.toolCount,
      iconUrl: item.iconUrl ?? undefined,
      isPublic: item.isPublic ?? undefined,
      createdBy: item.createdBy ?? undefined,
      creator: item.creator ?? undefined,
      slug: item.slug ?? "",
    }));

    const statusPriority: Record<string, number> = {
      created: 0,
      connected: 1,
      not_connected: 2,
    };

    return mapped.toSorted((a, b) => {
      const priorityA = statusPriority[a.status] ?? 3;
      const priorityB = statusPriority[b.status] ?? 3;

      if (priorityA !== priorityB) {
        return priorityA - priorityB;
      }

      return a.name.localeCompare(b.name);
    });
  }, [myIntegrationsData]);

  // Get status for a specific integration, derived from the /me catalog.
  const getIntegrationStatus = useCallback(
    (integrationId: string): IntegrationStatus | undefined => {
      const item = myIntegrationsData?.integrations.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      if (!item) return undefined;
      return {
        integrationId: item.id,
        connected: item.status === "connected",
      };
    },
    [myIntegrationsData],
  );

  // Connect integration
  const connectIntegration = useCallback(
    async (
      integrationId: string,
    ): Promise<{ status: string; name?: string; toolsCount?: number }> => {
      const integration = integrations.find(
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
          // Refetch all data
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["integrations"] }),
            queryClient.invalidateQueries({ queryKey: ["tools"] }),
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
        trackEvent(ANALYTICS_EVENTS.INTEGRATION_ERROR, {
          integration: integrationId,
          error: error instanceof Error ? error.message : "Unknown error",
        });
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
        trackEvent(ANALYTICS_EVENTS.INTEGRATION_DISCONNECTED, {
          integration: integrationId,
        });
        toast.success("Integration disconnected");
        // Invalidate (not refetch) so the UI updates in the background while
        // the modal closes immediately.
        queryClient.invalidateQueries({ queryKey: ["integrations"] });
        queryClient.invalidateQueries({ queryKey: ["tools"] });
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
      // Backend auto-connects and discovers tools, so refresh both caches.
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      queryClient.invalidateQueries({ queryKey: ["tools"] });
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
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      queryClient.invalidateQueries({ queryKey: ["tools"] });
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
        await queryClient.invalidateQueries({ queryKey: ["integrations"] });

        if (typeof window !== "undefined") {
          // Navigate to marketplace with refresh parameter to show published integration
          window.location.href = "/marketplace?refresh=true";
        }
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
        await queryClient.invalidateQueries({ queryKey: ["integrations"] });
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
  const refetch = useCallback(async () => {
    await queryClient.refetchQueries({ queryKey: ["integrations"] });
  }, [queryClient]);

  return {
    integrations,
    isLoading,
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
