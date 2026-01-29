import { create } from "zustand";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import { workflowApi } from "../api/workflowApi";

interface ExploreWorkflowsState {
  workflows: CommunityWorkflow[];
  isLoading: boolean;
  error: string | null;

  fetchExploreWorkflows: () => Promise<void>;
  clearError: () => void;
}

export const useExploreWorkflowsStore = create<ExploreWorkflowsState>(
  (set, get) => ({
    workflows: [],
    isLoading: false,
    error: null,

    fetchExploreWorkflows: async () => {
      const { isLoading } = get();

      // Skip if already loading
      if (isLoading) return;

      try {
        set({ isLoading: true, error: null });

        const response = await workflowApi.getExploreWorkflows(50, 0);
        set({ workflows: response.workflows });
      } catch (err) {
        set({
          error: (err as Error)?.message || "Failed to fetch explore workflows",
        });
      } finally {
        set({ isLoading: false });
      }
    },

    clearError: () => {
      set({ error: null });
    },
  }),
);
