import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { toast } from "@/lib/toast";

import { integrationsApi } from "../api/integrationsApi";
import type { IntegrationInstructions } from "../types";

/**
 * Load and save a single integration's custom instructions.
 *
 * The agent reads the same content from the user's account, so a save here is
 * reflected in the matching subagent's context on its next turn.
 */
export const useIntegrationInstructions = (integrationId: string) => {
  const queryClient = useQueryClient();
  const queryKey = ["integrations", "instructions", integrationId];

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => integrationsApi.getIntegrationInstructions(integrationId),
    staleTime: 0,
  });

  const mutation = useMutation({
    mutationFn: (content: string) =>
      integrationsApi.updateIntegrationInstructions(integrationId, content),
    onSuccess: (updated: IntegrationInstructions) => {
      queryClient.setQueryData(queryKey, updated);
      toast.success("Instructions saved");
    },
    onError: (error: unknown) => {
      toast.error(
        error instanceof Error ? error.message : "Failed to save instructions",
      );
    },
  });

  const save = useCallback(
    async (content: string) => {
      await mutation.mutateAsync(content);
    },
    [mutation],
  );

  return {
    instructions: data,
    isLoading,
    isSaving: mutation.isPending,
    save,
  };
};
