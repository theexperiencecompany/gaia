import type { EventProperties } from "@gaia/shared/analytics/events";
import { ApiError } from "@shared/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { track } from "@/lib/analytics";
import { apiErrorMessage } from "@/lib/api/errorMessage";
import { toast } from "@/lib/toast";
import { integrationsApi } from "../api/integrationsApi";
import { integrationQueries } from "../api/queries";
import { integrationKeys, toolKeys } from "../api/queryKeys";
import type {
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
  Integration,
  IntegrationConnectOptions,
  IntegrationStatus,
} from "../types";
import { byConnectionStateThenName, toIntegration } from "../utils/catalog";

/** The failure's status and machine code for integration:error; never its message, which can echo user input. */
function integrationFailure(
  integration: string,
  error: unknown,
): EventProperties["integration:error"] {
  if (!(error instanceof ApiError)) return { integration };
  return { integration, status: error.status, error_code: error.code };
}

/** The connect error's own copy (the API's words), or plain copy when the API never answered. */
function connectFailureMessage(
  error: unknown,
  integrationName: string,
): string {
  const fallback = `Couldn't connect ${integrationName}. Please try again.`;
  if (error instanceof ApiError) return apiErrorMessage(error) ?? fallback;
  return error instanceof Error && error.message ? error.message : fallback;
}

export interface UseIntegrationsReturn {
  // Data
  integrations: Integration[];
  isLoading: boolean;
  /** No catalogue yet (first paint, or the fetch has not started): show placeholders. */
  isPending: boolean;
  error: Error | null;

  // Helpers
  getIntegrationStatus: (
    integrationId: string,
  ) => IntegrationStatus | undefined;

  // Actions
  connectIntegration: (
    integrationId: string,
    options?: IntegrationConnectOptions,
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
 * Single hook for managing all integrations (platform + custom). Each
 * integration's status is the server's; this hook only sorts for display.
 */
export const useIntegrations = (): UseIntegrationsReturn => {
  const queryClient = useQueryClient();
  // The catalog is personalized and requires auth, so gate it on
  // isAuthenticated — public pages (marketplace, use-cases) must not fire 401s
  // for anonymous visitors.
  const { isAuthenticated } = useAuth();

  const {
    data: myIntegrationsData,
    isLoading,
    isPending,
    error,
  } = useQuery({
    ...integrationQueries.mine(),
    enabled: isAuthenticated,
  });

  // Sorted by state (expired → created → connected → not_connected) then name.
  const integrations = useMemo(
    (): Integration[] =>
      (myIntegrationsData?.integrations ?? [])
        .map(toIntegration)
        .toSorted(byConnectionStateThenName),
    [myIntegrationsData],
  );

  // Read the latest integrations inside callbacks without making the callbacks
  // depend on the array — otherwise every refetch changes their identity and
  // churns consumers (e.g. the sidebar content rebuilt on every poll tick).
  const integrationsRef = useRef(integrations);
  useEffect(() => {
    integrationsRef.current = integrations;
  });

  // One integration's status, as the server reported it.
  const getIntegrationStatus = useCallback(
    (integrationId: string): IntegrationStatus | undefined => {
      const integration = integrationsRef.current.find(
        (item) => item.id.toLowerCase() === integrationId.toLowerCase(),
      );
      if (!integration) return undefined;
      return {
        integrationId: integration.id,
        connected: integration.status === "connected",
        status: integration.status,
      };
    },
    [],
  );

  // Connect integration
  const connectIntegration = useCallback(
    async (
      integrationId: string,
      options?: IntegrationConnectOptions,
    ): Promise<{ status: string; name?: string; toolsCount?: number }> => {
      const integration = integrationsRef.current.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );
      const integrationName = integration?.name || "Integration";

      const toastId = toast.loading(`Connecting to ${integrationName}...`);

      try {
        const result = await integrationsApi.connectIntegration(
          integrationId,
          options,
        );

        if (result.status === "connected") {
          toast.success(`Connected to ${result.name}`, { id: toastId });
          // Invalidate (not awaited refetch) so the button/sidebar update in the
          // background instead of blocking on the catalog + tools GETs.
          queryClient.invalidateQueries({ queryKey: integrationKeys.all });
          queryClient.invalidateQueries({ queryKey: toolKeys.all });
        } else if (result.status === "redirecting") {
          // OAuth redirect in progress - dismiss toast, browser will navigate
          toast.dismiss(toastId);
        } else {
          // Handle unexpected status (e.g., failed, pending, etc.)
          toast.error(`Connection failed: ${result.status}`, { id: toastId });
        }

        return result;
      } catch (error) {
        toast.error(connectFailureMessage(error, integrationName), {
          id: toastId,
        });
        track("integration:error", integrationFailure(integrationId, error));
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
        toast.success("Integration disconnected");
        // Invalidate (not refetch) so the UI updates in the background while
        // the modal closes immediately.
        queryClient.invalidateQueries({ queryKey: integrationKeys.all });
        queryClient.invalidateQueries({ queryKey: toolKeys.all });
      } catch (error) {
        toast.error(
          `Failed to disconnect: ${error instanceof Error ? error.message : "Unknown error"}`,
        );
        track("integration:error", integrationFailure(integrationId, error));
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
      queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
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
      queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
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
        queryClient.invalidateQueries({ queryKey: integrationKeys.all });
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
    isLoading,
    isPending,
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
