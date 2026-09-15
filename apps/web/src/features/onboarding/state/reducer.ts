/**
 * Pure reducer for the onboarding flow. Every state mutation goes through
 * here — no component or effect mutates state directly. Action variants are
 * documented in `types.ts`.
 */

import { questions } from "../constants";
import { canSubmitNeeds, isAtNeedsCap } from "./derive";
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

    // The cap is enforced here, not only by dimming chips: a double tap or a
    // stale chip must never submit a third need the API would reject.
    case "toggleNeed": {
      if (state.selectedNeeds.includes(action.value)) {
        return {
          ...state,
          selectedNeeds: state.selectedNeeds.filter((n) => n !== action.value),
        };
      }
      if (isAtNeedsCap(state)) return state;
      return {
        ...state,
        selectedNeeds: [...state.selectedNeeds, action.value],
      };
    }

    case "setOtherNeed":
      return { ...state, otherNeed: action.value };

    // Opening "Something else" spends a pick, so it obeys the same cap as a
    // chip. Closing it clears the words: a field they can no longer see must
    // never be submitted.
    case "toggleOtherNeed": {
      if (state.otherNeedOpen)
        return { ...state, otherNeedOpen: false, otherNeed: "" };
      if (isAtNeedsCap(state)) return state;
      return { ...state, otherNeedOpen: true };
    }

    // Min-selection is enforced here, not only in the composer: the gate is
    // what the backend contract requires, so it lives with the transition.
    case "submitNeeds":
      if (!canSubmitNeeds(state)) return state;
      return { ...state, questionIndex: questions.length };

    case "preferencesPersisted":
      return { ...state, preferencesPersisted: true };

    case "ackPaidReveal":
      return { ...state, paidRevealAcked: true };

    case "platformConnected":
      return {
        ...state,
        connectedPlatform: action.platform,
        platformsConfirmed: true,
      };

    case "skipPlatforms":
      return { ...state, platformsConfirmed: true };

    case "introSeen":
      return { ...state, introSeen: true };

    // A restart replays the intro, so `introSeen` goes to a resolved false
    // rather than back to the unresolved null of a cold mount.
    case "restartStart":
      return { ...initialState, isRestarting: true, introSeen: false };

    case "restartDone":
      return { ...state, isRestarting: false };

    case "hydrate":
      return { ...state, ...action.partial };

    case "hydrated":
      return { ...state, hydratedFor: action.userId };

    case "reset":
      return initialState;
  }
}
