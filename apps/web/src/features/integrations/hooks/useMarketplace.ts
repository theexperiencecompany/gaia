/**
 * Hook for managing marketplace integrations and user workspace.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { toast } from "sonner";

import { integrationsApi } from "../api/integrationsApi";
import type {
  CreateCustomIntegrationRequest,
  MarketplaceIntegration,
  UserIntegration,
} from "../types";

export interface UseMarketplaceReturn {
  // Marketplace data
  featuredIntegrations: MarketplaceIntegration[];
  allIntegrations: MarketplaceIntegration[];
  isLoadingMarketplace: boolean;
  marketplaceError: Error | null;

  // User's integrations
  userIntegrations: UserIntegration[];
  isLoadingUserIntegrations: boolean;

  // Actions
  addToWorkspace: (integrationId: string) => Promise<void>;
  removeFromWorkspace: (integrationId: string) => Promise<void>;
  createCustomIntegration: (
    request: CreateCustomIntegrationRequest,
  ) => Promise<{ integration_id: string }>;
  deleteCustomIntegration: (integrationId: string) => Promise<void>;

  // Helpers
  isInWorkspace: (integrationId: string) => boolean;
  isConnected: (integrationId: string) => boolean;
  refreshMarketplace: () => void;
  refreshUserIntegrations: () => void;
}

export const useMarketplace = (category?: string): UseMarketplaceReturn => {
  const queryClient = useQueryClient();

  // Query for marketplace integrations
  const {
    data: marketplaceData,
    isLoading: isLoadingMarketplace,
    error: marketplaceError,
  } = useQuery({
    queryKey: ["marketplace", category],
    queryFn: () => integrationsApi.getMarketplace(category),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Query for user's integrations
  const { data: userIntegrationsData, isLoading: isLoadingUserIntegrations } =
    useQuery({
      queryKey: ["user-integrations"],
      queryFn: integrationsApi.getUserIntegrations,
    });

  const featuredIntegrations = useMemo(
    () => marketplaceData?.featured || [],
    [marketplaceData],
  );

  const allIntegrations = useMemo(
    () => marketplaceData?.integrations || [],
    [marketplaceData],
  );

  const userIntegrations = useMemo(
    () => userIntegrationsData?.integrations || [],
    [userIntegrationsData],
  );

  // Check if an integration is in user's workspace
  const isInWorkspace = useCallback(
    (integrationId: string): boolean => {
      return userIntegrations.some((ui) => ui.integration_id === integrationId);
    },
    [userIntegrations],
  );

  // Check if an integration is connected
  const isConnected = useCallback(
    (integrationId: string): boolean => {
      const userInt = userIntegrations.find(
        (ui) => ui.integration_id === integrationId,
      );
      return userInt?.status === "connected";
    },
    [userIntegrations],
  );

  // Add to workspace mutation
  const addMutation = useMutation({
    mutationFn: integrationsApi.addToWorkspace,
    onSuccess: (_, integrationId) => {
      toast.success("Integration added to workspace");
      queryClient.invalidateQueries({ queryKey: ["user-integrations"] });
      queryClient.invalidateQueries({ queryKey: ["integrations", "status"] });
    },
    onError: (error) => {
      toast.error(
        `Failed to add integration: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    },
  });

  // Remove from workspace mutation
  const removeMutation = useMutation({
    mutationFn: integrationsApi.removeFromWorkspace,
    onSuccess: (_, integrationId) => {
      toast.success("Integration removed from workspace");
      queryClient.invalidateQueries({ queryKey: ["user-integrations"] });
      queryClient.invalidateQueries({ queryKey: ["integrations", "status"] });
    },
    onError: (error) => {
      toast.error(
        `Failed to remove integration: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    },
  });

  // Create custom integration mutation
  const createMutation = useMutation({
    mutationFn: integrationsApi.createCustomIntegration,
    onSuccess: () => {
      toast.success("Custom integration created");
      queryClient.invalidateQueries({ queryKey: ["marketplace"] });
      queryClient.invalidateQueries({ queryKey: ["user-integrations"] });
    },
    onError: (error) => {
      toast.error(
        `Failed to create integration: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    },
  });

  // Delete custom integration mutation
  const deleteMutation = useMutation({
    mutationFn: integrationsApi.deleteCustomIntegration,
    onSuccess: () => {
      toast.success("Custom integration deleted");
      queryClient.invalidateQueries({ queryKey: ["marketplace"] });
      queryClient.invalidateQueries({ queryKey: ["user-integrations"] });
    },
    onError: (error) => {
      toast.error(
        `Failed to delete integration: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    },
  });

  const addToWorkspace = useCallback(
    async (integrationId: string) => {
      await addMutation.mutateAsync(integrationId);
    },
    [addMutation],
  );

  const removeFromWorkspace = useCallback(
    async (integrationId: string) => {
      await removeMutation.mutateAsync(integrationId);
    },
    [removeMutation],
  );

  const createCustomIntegration = useCallback(
    async (request: CreateCustomIntegrationRequest) => {
      return await createMutation.mutateAsync(request);
    },
    [createMutation],
  );

  const deleteCustomIntegration = useCallback(
    async (integrationId: string) => {
      await deleteMutation.mutateAsync(integrationId);
    },
    [deleteMutation],
  );

  const refreshMarketplace = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["marketplace"] });
  }, [queryClient]);

  const refreshUserIntegrations = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["user-integrations"] });
  }, [queryClient]);

  return {
    featuredIntegrations,
    allIntegrations,
    isLoadingMarketplace,
    marketplaceError: marketplaceError as Error | null,
    userIntegrations,
    isLoadingUserIntegrations,
    addToWorkspace,
    removeFromWorkspace,
    createCustomIntegration,
    deleteCustomIntegration,
    isInWorkspace,
    isConnected,
    refreshMarketplace,
    refreshUserIntegrations,
  };
};
