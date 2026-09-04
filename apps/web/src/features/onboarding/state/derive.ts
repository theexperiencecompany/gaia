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

import { NEEDS_MIN_SELECTION, questions } from "../constants";
import type { OnboardingState, Stage } from "./types";

function isQuestionsComplete(s: OnboardingState): boolean {
  return s.questionIndex >= questions.length;
}

export function canSubmitNeeds(s: OnboardingState): boolean {
  return (
    s.selectedNeeds.length >= NEEDS_MIN_SELECTION || s.otherNeed.trim() !== ""
  );
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
