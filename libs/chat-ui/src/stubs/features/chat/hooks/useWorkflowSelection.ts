/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type {
  SelectedWorkflowData,
  WorkflowSelectionOptions,
} from "@/stores/workflowSelectionStore";

export type { SelectedWorkflowData, WorkflowSelectionOptions };

const noop = () => {};

export const useWorkflowSelection = () => ({
  selectedWorkflow: null as SelectedWorkflowData | null,
  selectWorkflow: noop as (
    workflow: SelectedWorkflowData,
    options?: WorkflowSelectionOptions,
  ) => void,
  clearSelectedWorkflow: noop as () => void,
  setSelectedWorkflow: noop as (
    workflow: SelectedWorkflowData | null,
  ) => void,
});
