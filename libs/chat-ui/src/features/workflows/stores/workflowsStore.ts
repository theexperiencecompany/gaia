import { create } from "zustand";

import { type Workflow, workflowApi } from "../api/workflowApi";

const CACHE_TTL = 60 * 1000; // 1 minute in milliseconds

interface WorkflowsState {
  workflows: Workflow[];
  isLoading: boolean;
  error: string | null;
  lastFetched: number | null;

  fetchWorkflows: () => Promise<void>;
  addWorkflow: (workflow: Workflow) => void;
  updateWorkflow: (workflowId: string, updates: Partial<Workflow>) => void;
  removeWorkflow: (workflowId: string) => void;
  setWorkflows: (workflows: Workflow[]) => void;
  clearError: () => void;
}

export const useWorkflowsStore = create<WorkflowsState>((set, get) => ({
  workflows: [],
  isLoading: false,
  error: null,
  lastFetched: null,

  fetchWorkflows: async () => {
    const { isLoading, lastFetched } = get();

    // Skip if already loading
    if (isLoading) return;

    // Skip if cache is still fresh
    if (lastFetched && Date.now() - lastFetched < CACHE_TTL) {
      return;
    }

    try {
      set({ isLoading: true, error: null });

      const response = await workflowApi.listWorkflows();
      set({
        workflows: response.workflows,
        lastFetched: Date.now(),
      });
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to fetch workflows";
      set({ error: errorMessage });
    } finally {
      set({ isLoading: false });
    }
  },

  addWorkflow: (workflow) => {
    set((state) => ({
      workflows: [workflow, ...state.workflows],
    }));
  },

  updateWorkflow: (workflowId, updates) => {
    set((state) => ({
      workflows: state.workflows.map((workflow) =>
        workflow.id === workflowId ? { ...workflow, ...updates } : workflow,
      ),
    }));
  },

  removeWorkflow: (workflowId) => {
    set((state) => ({
      workflows: state.workflows.filter(
        (workflow) => workflow.id !== workflowId,
      ),
    }));
  },

  setWorkflows: (workflows) => {
    set({ workflows, lastFetched: Date.now() });
  },

  clearError: () => {
    set({ error: null });
  },
}));
