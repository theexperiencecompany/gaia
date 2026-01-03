import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

import type { Workflow } from "@/features/workflows/api/workflowApi";

export interface SelectedWorkflowData {
  id: string;
  title: string;
  description: string;
  steps: Array<{
    id: string;
    title: string;
    description: string;
    category: string;
  }>;
}

export interface WorkflowSelectionOptions {
  autoSend?: boolean;
}

interface WorkflowSelectionState {
  selectedWorkflow: SelectedWorkflowData | null;
  autoSend: boolean;
}

interface WorkflowSelectionActions {
  selectWorkflow: (
    workflow: Workflow | SelectedWorkflowData,
    options?: WorkflowSelectionOptions,
  ) => void;
  clearSelectedWorkflow: () => void;
  setSelectedWorkflow: (workflow: SelectedWorkflowData | null) => void;
  setAutoSend: (autoSend: boolean) => void;
}

type WorkflowSelectionStore = WorkflowSelectionState & WorkflowSelectionActions;

const initialState: WorkflowSelectionState = {
  selectedWorkflow: null,
  autoSend: false,
};

export const useWorkflowSelectionStore = create<WorkflowSelectionStore>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,

        selectWorkflow: (workflow, options) => {
          const workflowData: SelectedWorkflowData =
            "trigger_config" in workflow
              ? {
                  id: workflow.id,
                  title: workflow.title,
                  description: workflow.description,
                  steps: workflow.steps.map((step) => ({
                    id: step.id,
                    title: step.title,
                    description: step.description,
                    category: step.category,
                  })),
                }
              : workflow;

          set(
            {
              selectedWorkflow: workflowData,
              autoSend: options?.autoSend || false,
            },
            false,
            "selectWorkflow",
          );
        },

        clearSelectedWorkflow: () =>
          set(
            {
              selectedWorkflow: null,
              autoSend: false,
            },
            false,
            "clearSelectedWorkflow",
          ),

        setSelectedWorkflow: (selectedWorkflow) =>
          set({ selectedWorkflow }, false, "setSelectedWorkflow"),

        setAutoSend: (autoSend) => set({ autoSend }, false, "setAutoSend"),
      }),
      {
        name: "workflow-selection-storage",
        partialize: (state) => ({
          selectedWorkflow: state.selectedWorkflow,
        }),
      },
    ),
    { name: "workflow-selection-store" },
  ),
);

// Selectors
export const useSelectedWorkflow = () =>
  useWorkflowSelectionStore((state) => state.selectedWorkflow);
export const useWorkflowAutoSend = () =>
  useWorkflowSelectionStore((state) => state.autoSend);
