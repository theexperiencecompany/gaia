/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { Workflow } from "@/features/workflows/api/workflowApi";

export interface SelectedWorkflowData {
  id: string;
  title: string;
  description: string;
  prompt?: string;
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

const noop = () => {};

const frozenState: WorkflowSelectionStore = Object.freeze({
  selectedWorkflow: null,
  autoSend: false,
  selectWorkflow: noop,
  clearSelectedWorkflow: noop,
  setSelectedWorkflow: noop,
  setAutoSend: noop,
});

type Selector<U> = (state: WorkflowSelectionStore) => U;

interface UseStoreFn {
  <U>(selector: Selector<U>): U;
  (): WorkflowSelectionStore;
  getState: () => WorkflowSelectionStore;
  setState: (partial: Partial<WorkflowSelectionStore>) => void;
  subscribe: (listener: (state: WorkflowSelectionStore) => void) => () => void;
}

export const useWorkflowSelectionStore: UseStoreFn = (<U,>(
  selector?: Selector<U>,
) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseStoreFn;
useWorkflowSelectionStore.getState = () => frozenState;
useWorkflowSelectionStore.setState = noop;
useWorkflowSelectionStore.subscribe = () => noop;
