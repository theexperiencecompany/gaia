/**
 * Pure reducer for the onboarding flow. Every state mutation goes through
 * here — no component or effect mutates state directly. Action variants are
 * documented in `types.ts`.
 */

import { questions } from "../constants";
import { canSubmitNeeds } from "./derive";
import { initialState } from "./initial";
import type { Action, OnboardingState } from "./types";

export function reducer(
  state: OnboardingState,
  action: Action,
): OnboardingState {
  switch (action.type) {
    case "draftProfession":
      return { ...state, draftProfession: action.value };

    case "answer": {
      const isLast = state.questionIndex >= questions.length - 1;
      return {
        ...state,
        responses: { ...state.responses, [action.field]: action.value },
        questionIndex: isLast ? questions.length : state.questionIndex + 1,
        draftProfession: null,
      };
    }

    case "toggleNeed": {
      const selected = state.selectedNeeds.includes(action.value)
        ? state.selectedNeeds.filter((n) => n !== action.value)
        : [...state.selectedNeeds, action.value];
      return { ...state, selectedNeeds: selected };
    }

    // Min-selection is enforced here, not only in the composer: the gate is
    // what the backend contract requires, so it lives with the transition.
    case "submitNeeds":
      if (!canSubmitNeeds(state)) return state;
      return { ...state, questionIndex: questions.length };

    case "ackPaidReveal":
      return { ...state, paidRevealAcked: true };

    case "ackGreeting":
      return { ...state, greetingAcked: true };

    case "platformConnected":
      return {
        ...state,
        connectedPlatform: action.platform,
        platformsConfirmed: true,
      };

    case "skipPlatforms":
      return { ...state, platformsConfirmed: true };

    case "restartStart":
      return { ...initialState, isRestarting: true };

    case "restartDone":
      return { ...state, isRestarting: false };

    case "hydrate":
      return { ...state, ...action.partial };

    case "reset":
      return initialState;
  }
}
