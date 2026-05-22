/**
 * Pure helpers for the clarify stage. Kept out of the component file so the
 * composer stays focused on layout + dispatch wiring, and so the helpers can
 * be reused by the demo page or future selectors without dragging React in.
 */

import type { OnboardingState } from "../state/types";
import type { ClarifyAnswer, ClarifyQuestion } from "../types";

export const OPTION_VALUE_PREFIX = "opt:";
export const OTHER_VALUE = "__other__";
export const SKIP_VALUE = "__skip__";

export const CLARIFY_RADIO_BASE_CLASS =
  "m-0 max-w-none rounded-xl border-0 bg-zinc-800/60 p-2 data-[selected=true]:bg-zinc-800";

export const CLARIFY_RADIO_LABEL_CLASS = "text-sm text-zinc-200";
export const CLARIFY_RADIO_LABEL_MUTED_CLASS = "text-sm text-zinc-400";

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

// A non-empty in-flight draft counts as answered so the user can submit
// without an extra blur step.
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
