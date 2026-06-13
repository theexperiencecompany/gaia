import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { FEATURE_DISCOVERED_WORKFLOWS_KEY } from "@/features/chat/constants";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import { usePathname } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
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

      // Navigate to chat page if not already there. This MUST happen before
      // analytics — a throwing/blocked analytics SDK must never prevent the
      // user from reaching the chat where the workflow auto-runs.
      if (pathname !== "/c") {
        router.push("/c");
      }

      // Track first workflow use as feature discovery (best-effort).
      try {
        const hasTrackedFeatureDiscovered =
          typeof globalThis.window !== "undefined" &&
          localStorage.getItem(FEATURE_DISCOVERED_WORKFLOWS_KEY);

        if (!hasTrackedFeatureDiscovered) {
          trackEvent(ANALYTICS_EVENTS.FEATURE_DISCOVERED, {
            feature: "workflows",
            workflow_title: workflow.title,
          });

          if (typeof globalThis.window !== "undefined") {
            localStorage.setItem(FEATURE_DISCOVERED_WORKFLOWS_KEY, "true");
          }
        }
      } catch (error) {
        console.error("Failed to track workflow feature discovery:", error);
      }
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
