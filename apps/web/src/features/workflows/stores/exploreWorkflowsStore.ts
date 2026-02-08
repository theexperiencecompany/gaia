import { create } from "zustand";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import { workflowApi } from "../api/workflowApi";

const CACHE_TTL = 5 * 60 * 1000; // 5 minutes - explore workflows change less frequently

interface ExploreWorkflowsState {
  workflows: CommunityWorkflow[];
  isLoading: boolean;
  error: string | null;
  lastFetched: number | null;

  fetchExploreWorkflows: () => Promise<void>;
  clearError: () => void;
}

export const useExploreWorkflowsStore = create<ExploreWorkflowsState>(
  (set, get) => ({
    workflows: [],
    isLoading: false,
    error: null,
    lastFetched: null,

    fetchExploreWorkflows: async () => {
      const { isLoading, lastFetched } = get();

      // Skip if already loading
      if (isLoading) return;

      // Skip if cache is still fresh
      if (lastFetched && Date.now() - lastFetched < CACHE_TTL) {
        return;
      }

      try {
        set({ isLoading: true, error: null });

        const response = await workflowApi.getExploreWorkflows(50, 0);
        set({ workflows: response.workflows, lastFetched: Date.now() });
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
