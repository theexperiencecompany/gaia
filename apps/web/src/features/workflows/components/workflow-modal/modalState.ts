export interface WorkflowModalUiState {
  creationPhase: "form" | "creating" | "generating" | "success" | "error";
  /**
   * Rendered by the steps panel. No code path sets it today — initial step
   * generation runs through `isRegeneratingSteps` — but the panel still reads
   * it, so it stays part of the modal's UI state rather than being dropped.
   */
  isGeneratingSteps: boolean;
  isRegeneratingSteps: boolean;
  regenerationError: string | null;
  isTogglingActivation: boolean;
  isActivated: boolean;
}

export type WorkflowModalUiAction =
  | { type: "phase"; phase: WorkflowModalUiState["creationPhase"] }
  | { type: "regenerating"; value: boolean }
  | { type: "regenerationError"; message: string | null }
  | { type: "togglingActivation"; value: boolean }
  | { type: "activated"; value: boolean }
  | { type: "resetToForm" };

export const initialWorkflowModalUiState: WorkflowModalUiState = {
  creationPhase: "form",
  isGeneratingSteps: false,
  isRegeneratingSteps: false,
  regenerationError: null,
  isTogglingActivation: false,
  isActivated: true,
};

export function workflowModalUiReducer(
  state: WorkflowModalUiState,
  action: WorkflowModalUiAction,
): WorkflowModalUiState {
  switch (action.type) {
    case "phase":
      return { ...state, creationPhase: action.phase };
    case "regenerating":
      return { ...state, isRegeneratingSteps: action.value };
    case "regenerationError":
      return { ...state, regenerationError: action.message };
    case "togglingActivation":
      return { ...state, isTogglingActivation: action.value };
    case "activated":
      return { ...state, isActivated: action.value };
    case "resetToForm":
      return {
        ...state,
        creationPhase: "form",
        isRegeneratingSteps: false,
        regenerationError: null,
      };
  }
}
