import { describe, expect, it } from "vitest";

import {
  initialWorkflowModalUiState,
  workflowModalUiReducer,
} from "./modalState";

describe("workflowModalUiReducer", () => {
  it("moves through the creation phases", () => {
    const creating = workflowModalUiReducer(initialWorkflowModalUiState, {
      type: "phase",
      phase: "creating",
    });
    expect(creating.creationPhase).toBe("creating");

    const success = workflowModalUiReducer(creating, {
      type: "phase",
      phase: "success",
    });
    expect(success.creationPhase).toBe("success");
  });

  it("tracks the regeneration flag and its error independently", () => {
    const regenerating = workflowModalUiReducer(initialWorkflowModalUiState, {
      type: "regenerating",
      value: true,
    });
    const failed = workflowModalUiReducer(regenerating, {
      type: "regenerationError",
      message: "boom",
    });
    expect(failed).toMatchObject({
      isRegeneratingSteps: true,
      regenerationError: "boom",
    });
  });

  it("tracks activation and its in-flight toggle", () => {
    const toggling = workflowModalUiReducer(initialWorkflowModalUiState, {
      type: "togglingActivation",
      value: true,
    });
    const activated = workflowModalUiReducer(toggling, {
      type: "activated",
      value: false,
    });
    expect(activated).toMatchObject({
      isTogglingActivation: true,
      isActivated: false,
    });
  });

  it("resetToForm clears the phase, regeneration flag and error but keeps activation", () => {
    const dirty = workflowModalUiReducer(
      {
        ...initialWorkflowModalUiState,
        creationPhase: "error",
        isRegeneratingSteps: true,
        regenerationError: "boom",
        isTogglingActivation: true,
        isActivated: false,
      },
      { type: "resetToForm" },
    );

    expect(dirty).toEqual({
      creationPhase: "form",
      isGeneratingSteps: false,
      isRegeneratingSteps: false,
      regenerationError: null,
      isTogglingActivation: true,
      isActivated: false,
    });
  });
});
