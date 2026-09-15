import type { OnboardingData } from "@/features/auth/api/authApi";
/**
 * Linear stage cursor over the fixed queue (Q1/Q2, payment, receipt, platform
 * pick, chat handoff) — forward only, never sideways. `getStage` returns the
 * first stage not yet past; payment's "done" lives outside this state (true
 * when the backend reports the user subscribed). `isPaid` must be definitive —
 * while unknown, `useIsPaid().isPaid` is false, parking the user on payment's neutral loading state rather than skipping an unchecked gate.
 */

import {
  FIELD_NAMES,
  isKnownNeed,
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
 * The answers the account already gave, as a wizard draft — what a browser
 * with no cache resumes from, instead of re-asking Q1/Q2 and overwriting them.
 *
 * `null` means the account has answered nothing (also the signal a local
 * draft's `preferencesPersisted` is stale). `GET /user/me` reports unset
 * onboarding as `preferences: {}`, never a missing field, so presence alone says nothing — a recorded profession is the first thing saved.
 */
export function draftFromServerPreferences(
  onboarding: OnboardingData | undefined,
): Partial<OnboardingState> | null {
  const preferences = onboarding?.preferences;
  if (!preferences?.profession) return null;

  const otherNeed = preferences.other_need ?? "";
  return {
    responses: { [FIELD_NAMES.PROFESSION]: preferences.profession },
    questionIndex: questions.length,
    // A need the API no longer accepts must not come back as a chip.
    selectedNeeds: (preferences.needs ?? []).filter(isKnownNeed),
    otherNeed,
    otherNeedOpen: otherNeed !== "",
    preferencesPersisted: true,
  };
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
