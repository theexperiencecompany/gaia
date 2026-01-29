import { useEffect } from "react";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import { useExploreWorkflowsStore } from "../stores/exploreWorkflowsStore";

interface UseExploreWorkflowsReturn {
  workflows: CommunityWorkflow[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  clearError: () => void;
}

export const useExploreWorkflows = (
  autoFetch: boolean = true,
): UseExploreWorkflowsReturn => {
  const { workflows, isLoading, error, fetchExploreWorkflows, clearError } =
    useExploreWorkflowsStore();

  useEffect(() => {
    if (autoFetch) {
      fetchExploreWorkflows();
    }
  }, [autoFetch, fetchExploreWorkflows]);

  return {
    workflows,
    isLoading,
    error,
    refetch: fetchExploreWorkflows,
    clearError,
  };
};
