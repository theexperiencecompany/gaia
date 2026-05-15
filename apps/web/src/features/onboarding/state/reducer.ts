/**
 * Pure reducer for the onboarding flow. Every state mutation goes through
 * here — no component or effect mutates state directly. Action variants are
 * documented in `types.ts`.
 */

import { questions } from "../constants";
import type { OnboardingStage } from "../types/websocket";
import { initialState } from "./initial";
import type { Action, OnboardingState } from "./types";

/**
 * When a `*_ready` / completion stage fires, the matching in-flight progress
 * slots are no longer relevant — drop them so the UI can't display stale text
 * after the step has completed.
 *
 * `inbox_scanning` is a multi-emit stage with no dedicated completion event;
 * any "after-inbox" stage signals it's done.
 */
const PROGRESS_CLEARED_BY: Partial<
  Record<OnboardingStage, readonly OnboardingStage[]>
> = {
  writing_style_ready: ["writing_style_progress"],
  triage_ready: ["triage_analyzing", "inbox_scanning"],
  todos_ready: ["todos_creating", "inbox_scanning"],
  workflows_ready: ["workflows_creating", "inbox_scanning"],
  social_profiles_ready: ["inbox_scanning"],
  complete: [
    "inbox_scanning",
    "writing_style_progress",
    "triage_analyzing",
    "todos_creating",
    "workflows_creating",
  ],
};

function clearProgressSlots(
  progressByStage: OnboardingState["progressByStage"],
  completed: OnboardingStage,
): OnboardingState["progressByStage"] {
  const toClear = PROGRESS_CLEARED_BY[completed];
  if (!toClear) return progressByStage;
  let next: OnboardingState["progressByStage"] | null = null;
  for (const stage of toClear) {
    if (stage in progressByStage) {
      next = next ?? { ...progressByStage };
      delete next[stage];
    }
  }
  return next ?? progressByStage;
}

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

    case "serverSnapshot":
      return { ...state, server: action.data };

    case "serverPatch":
      return {
        ...state,
        server: { ...(state.server ?? {}), ...action.patch },
      };

    case "progress":
      return {
        ...state,
        progressByStage: {
          ...state.progressByStage,
          [action.stage]: action.message,
        },
      };

    case "stageComplete": {
      const alreadyMarked = state.completedStages.has(action.stage);
      const nextProgress = clearProgressSlots(
        state.progressByStage,
        action.stage,
      );
      if (alreadyMarked && nextProgress === state.progressByStage) {
        return state;
      }
      const completedStages = alreadyMarked
        ? state.completedStages
        : new Set(state.completedStages).add(action.stage);
      return {
        ...state,
        completedStages,
        progressByStage: nextProgress,
      };
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
        platformsConfirmed: true,
      };

    case "skipPlatforms":
      return { ...state, platformsConfirmed: true };

    case "executeTodo":
      return {
        ...state,
        todoExecutionStarted: true,
        todoExecutionMessage: action.message,
        todoExecutionConvoId: action.convoId,
        todoExecutionTodo: action.todo,
      };

    case "clearTodoExecutionMessage":
      return { ...state, todoExecutionMessage: null };

    case "ackTodoDemo":
      return { ...state, ackedTodos: true };

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
