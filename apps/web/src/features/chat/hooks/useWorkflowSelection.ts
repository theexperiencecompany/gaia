import { usePathname, useRouter } from "next/navigation";
import { useCallback } from "react";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import { trackFeatureDiscovery } from "@/lib/analytics";
import {
  type SelectedWorkflowData,
  useWorkflowSelectionStore,
  type WorkflowSelectionOptions,
} from "@/stores/workflowSelectionStore";

export type { SelectedWorkflowData, WorkflowSelectionOptions };

export const useWorkflowSelection = () => {
  const {
    selectedWorkflow,
    selectWorkflow: storeSelectWorkflow,
    clearSelectedWorkflow,
    setSelectedWorkflow,
  } = useWorkflowSelectionStore();
  const router = useRouter();
  const pathname = usePathname();

  const selectWorkflow = useCallback(
    (
      workflow: Workflow | SelectedWorkflowData,
      options?: WorkflowSelectionOptions,
    ) => {
      // Use store to persist the workflow selection
      storeSelectWorkflow(workflow, options);

      // Track first workflow use as feature discovery
      trackFeatureDiscovery("workflows", { workflow_title: workflow.title });

      // Navigate to chat page if not already there
      if (pathname !== "/c") router.push("/c");
    },
    [storeSelectWorkflow, pathname, router],
  );

  return {
    selectedWorkflow,
    selectWorkflow,
    clearSelectedWorkflow,
    setSelectedWorkflow,
  };
};
