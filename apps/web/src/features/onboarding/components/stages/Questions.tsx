/**
 * `questions` stage. Active until Q1 (profession) and Q2 (needs) are both
 * answered. The transcript renders in `MessagesRegion`; this file owns the
 * user's reply to the active question, rendered in the thread on their side.
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

export function QuestionsReply({ state, dispatch }: QuestionsProps) {
  const currentQuestion = questions[state.questionIndex];

  const handleSelectProfession = useCallback(
    (value: string) => dispatch({ type: "draftProfession", value }),
    [dispatch],
  );

  const { draftProfession } = state;
  const handleSubmitProfession = useCallback(() => {
    if (!draftProfession) return;
    dispatch({
      type: "answer",
      field: FIELD_NAMES.PROFESSION,
      value: draftProfession,
    });
  }, [dispatch, draftProfession]);

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
      draftProfession={draftProfession}
      onSelectProfession={handleSelectProfession}
      onContinue={handleSubmitProfession}
    />
  );
}
