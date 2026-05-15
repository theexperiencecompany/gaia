/**
 * Pure helpers for the clarify stage. Kept out of the component file so the
 * composer stays focused on layout + dispatch wiring, and so the helpers can
 * be reused by the demo page or future selectors without dragging React in.
 */

import type { OnboardingState } from "../state/types";
import type { ClarifyAnswer, ClarifyQuestion } from "../types";

/** Sentinel radio values for the "Other" and "Skip" rows. */
export const OPTION_VALUE_PREFIX = "opt:";
export const OTHER_VALUE = "__other__";
export const SKIP_VALUE = "__skip__";

/**
 * Shared `classNames` payload for every Radio row in the clarify composer.
 * Centralised so the four rows (3 options + Other + Skip) stay visually
 * identical — the Skip row only overrides the label colour.
 */
export const CLARIFY_RADIO_BASE_CLASS =
  "m-0 max-w-none rounded-xl border-0 bg-zinc-800/60 p-2 data-[selected=true]:bg-zinc-800";

export const CLARIFY_RADIO_LABEL_CLASS = "text-sm text-zinc-200";
export const CLARIFY_RADIO_LABEL_MUTED_CLASS = "text-sm text-zinc-400";

/**
 * Resolves the radio value the RadioGroup should highlight, given the current
 * committed answer and any in-flight "Other" draft. Returning `null` means no
 * row is selected yet.
 *
 * Order of precedence: committed option → committed custom → skip → pending
 * "Other" selection (flagged by `clarifyOtherSelected`, set when the user
 * clicks the Other radio but hasn't typed/committed yet).
 */
export function radioValueFor(
  question: ClarifyQuestion,
  answer: ClarifyAnswer | undefined,
  otherSelected: boolean,
): string | null {
  if (answer?.kind === "option" && answer.value) {
    const idx = question.options.indexOf(answer.value);
    return idx >= 0 ? `${OPTION_VALUE_PREFIX}${idx}` : null;
  }
  if (answer?.kind === "custom" && answer.value) return OTHER_VALUE;
  if (answer?.kind === "skip") return SKIP_VALUE;
  if (otherSelected) return OTHER_VALUE;
  return null;
}

/**
 * Whether a single question is satisfied (option picked, custom committed,
 * or explicitly skipped). Also treats an in-flight non-empty draft as
 * answered so the user can submit without an extra blur step.
 */
export function isQuestionAnswered(
  answer: ClarifyAnswer | undefined,
  draft: string | undefined,
): boolean {
  if (!answer) return !!draft?.trim();
  if (answer.kind === "skip") return true;
  if (answer.kind === "option") return !!answer.value;
  if (answer.kind === "custom") return !!answer.value?.trim();
  return false;
}

/**
 * Number of clarify questions the user has answered. Used by the composer
 * header counter and the demo page status row — extracting it kills the
 * duplicate `Object.keys(...).filter(...)` inline computation.
 */
export function countAnsweredClarify(state: OnboardingState): number {
  const questions = state.clarifyQuestions ?? [];
  let count = 0;
  for (const q of questions) {
    if (
      isQuestionAnswered(
        state.clarifyAnswers[q.id],
        state.clarifyCustomDrafts[q.id],
      )
    ) {
      count += 1;
    }
  }
  return count;
}
