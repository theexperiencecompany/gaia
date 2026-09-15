import type { OnboardingData } from "@/features/auth/api/authApi";
/**
 * Linear stage cursor. The flow is a fixed queue — Q1/Q2, then payment,
 * then the receipt, the platform pick and finally the
 * handoff into chat. The user advances forward only, never sideways.
 *
 * `getStage` returns the first stage the user is not past. Payment is the
 * only stage whose "done" answer lives outside this state: it is done when
 * the backend says the user is subscribed, which is also why an already
 * subscribed user never sees it.
 *
 * `isPaid` must be the *definitive* answer — `useIsPaid().isPaid` is false
 * while the subscription status is still unknown, which parks the user on
 * the payment stage (where the stage itself renders a neutral loading
 * state) rather than advancing them past a gate that was never checked.
 */

import {
  NEEDS_MAX_SELECTION,
  NEEDS_MIN_SELECTION,
  questions,
} from "../constants";
import type { OnboardingState, Stage } from "./types";

function isQuestionsComplete(s: OnboardingState): boolean {
  return s.questionIndex >= questions.length;
}

/** Q2 picks so far: chips plus "Something else" once its field is open. */
function pickCount(s: OnboardingState): number {
  return s.selectedNeeds.length + (s.otherNeedOpen ? 1 : 0);
}

/** Whether Q2 has spent all its picks. The reducer refuses further picks on
 * this; the chip row only reads it to dim what can no longer be chosen. */
export function isAtNeedsCap(s: OnboardingState): boolean {
  return pickCount(s) >= NEEDS_MAX_SELECTION;
}

export function canSubmitNeeds(s: OnboardingState): boolean {
  return (
    s.selectedNeeds.length >= NEEDS_MIN_SELECTION || s.otherNeed.trim() !== ""
  );
}

/**
 * Whether the account has the answers the wizard's "preferences persisted"
 * flag claims. `GET /user/me` reports an unset onboarding as
 * `preferences: {}`, never as a missing field, so presence of the object
 * says nothing; a recorded profession is the first thing the wizard saves.
 */
export function serverHasRecordedPreferences(
  onboarding: OnboardingData | undefined,
): boolean {
  return Boolean(onboarding?.preferences?.profession);
}

export function getStage(s: OnboardingState, isPaid: boolean): Stage {
  if (!isQuestionsComplete(s)) return "questions";
  if (!isPaid) return "payment";
  if (!s.paidRevealAcked) return "paidReveal";
  if (!s.platformsConfirmed) return "platformPick";
  return "chat";
}

const STAGE_PROGRESS: Record<Stage, number> = {
  questions: 0,
  payment: 2,
  paidReveal: 3,
  platformPick: 4,
  chat: 5,
};

export const PROGRESS_TOTAL_STEPS = 5;

export function getProgress(s: OnboardingState, stage: Stage): number {
  if (s.isRestarting) return 0;
  if (stage === "questions") return s.questionIndex;
  return STAGE_PROGRESS[stage];
}
