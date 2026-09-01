/**
 * `questions` stage. Active until Q1 (profession) and Q2 (needs) are both
 * answered. The transcript renders in `MessagesRegion`; this file only owns
 * the active question's composer.
 */

"use client";

import type { Dispatch } from "react";
import { useCallback } from "react";
import { FIELD_NAMES, questions } from "../../constants";
import { canSubmitNeeds } from "../../state/derive";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingInput } from "../OnboardingInput";

interface QuestionsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function QuestionsComposer({ state, dispatch }: QuestionsProps) {
  const currentQuestion = questions[state.questionIndex];

  const handleProfessionInputChange = useCallback(
    (value: string) => {
      dispatch({ type: "draftProfession", value: value || null });
    },
    [dispatch],
  );

  const handleProfessionSelect = useCallback(
    (key: React.Key | null) => {
      const value = key != null ? String(key) : null;
      dispatch({ type: "draftProfession", value });
      if (value) {
        dispatch({ type: "answer", field: FIELD_NAMES.PROFESSION, value });
      }
    },
    [dispatch],
  );

  const handleToggleNeed = useCallback(
    (value: string) => dispatch({ type: "toggleNeed", value }),
    [dispatch],
  );

  const handleSubmitNeeds = useCallback(
    () => dispatch({ type: "submitNeeds" }),
    [dispatch],
  );

  if (currentQuestion?.fieldName === FIELD_NAMES.NEEDS) {
    return (
      <OnboardingInput
        mode="needs"
        selectedNeeds={state.selectedNeeds}
        canContinue={canSubmitNeeds(state)}
        onToggleNeed={handleToggleNeed}
        onContinue={handleSubmitNeeds}
      />
    );
  }

  if (!currentQuestion) return null;

  return (
    <OnboardingInput
      mode="profession"
      draftProfession={state.draftProfession}
      onProfessionSelect={handleProfessionSelect}
      onProfessionInputChange={handleProfessionInputChange}
    />
  );
}
