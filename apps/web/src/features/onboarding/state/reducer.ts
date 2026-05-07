/**
 * Pure reducer for the onboarding flow. Every state mutation goes through
 * here — no component or effect mutates state directly. Action variants are
 * documented in `types.ts`.
 */

import { questions } from "../constants";
import { initialState } from "./initial";
import type { Action, OnboardingState } from "./types";

export function reducer(
  state: OnboardingState,
  action: Action,
): OnboardingState {
  switch (action.type) {
    case "draftText":
      return { ...state, draftText: action.value };

    case "draftProfession":
      return { ...state, draftProfession: action.value };

    case "answer": {
      const responses = {
        ...state.responses,
        [action.field]: action.value,
      };
      const isLast = state.questionIndex >= questions.length - 1;
      return {
        ...state,
        responses,
        questionIndex: isLast ? questions.length : state.questionIndex + 1,
        draftText: "",
        draftProfession: null,
      };
    }

    case "submitError":
      return { ...state, submissionError: true };

    case "retrySubmit":
      return { ...state, submissionError: false };

    case "serverSnapshot":
      return { ...state, server: action.data };

    case "serverPatch":
      return {
        ...state,
        server: { ...(state.server ?? {}), ...action.patch },
      };

    case "progress":
      return { ...state, progressMessage: action.message };

    case "stageComplete": {
      if (state.completedStages.has(action.stage)) return state;
      const next = new Set(state.completedStages);
      next.add(action.stage);
      return { ...state, completedStages: next };
    }

    case "ackWriting":
      return { ...state, ackedWritingStyle: true };

    case "ackTodos":
      return { ...state, ackedTodos: true };

    case "confirmWorkflows":
      return { ...state, workflowsConfirmed: true };

    case "platformConnected":
      return {
        ...state,
        connectedPlatform: action.platform,
        workflowsConfirmed: true,
      };

    case "executeTodo":
      return {
        ...state,
        ackedTodos: true,
        todoExecutionMessage: action.message,
      };

    case "clearTodoExecutionMessage":
      return { ...state, todoExecutionMessage: null };

    case "restartStart":
      return {
        ...initialState,
        isRestarting: true,
      };

    case "restartDone":
      return { ...state, isRestarting: false };

    case "hydrate":
      return { ...state, ...action.partial };

    case "reset":
      return initialState;
  }
}
