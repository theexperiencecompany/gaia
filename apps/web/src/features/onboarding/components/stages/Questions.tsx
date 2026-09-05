/**
 * `questions` stage. Active until Q1 (profession) and Q2 (needs) are both
 * answered. The transcript renders in `MessagesRegion`; this file owns the
 * user's reply to the active question, rendered in the thread on their side.
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useCallback } from "react";
import { FIELD_NAMES, questions } from "../../constants";
import { MOTION_FADE_UP } from "../../constants/motion";
import { usePaceDone } from "../../hooks/useTypedLines";
import { canSubmitNeeds } from "../../state/derive";
import { questionRevealKey } from "../../state/paceStore";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingInput } from "../OnboardingInput";

interface QuestionsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function QuestionsReply({ state, dispatch }: QuestionsProps) {
  const currentQuestion = questions[state.questionIndex];
  // The reply only shows up once GAIA has finished "typing" the question.
  const gaiaDone = usePaceDone(questionRevealKey(currentQuestion?.id ?? ""));

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

  const handleOtherNeedChange = useCallback(
    (value: string) => dispatch({ type: "setOtherNeed", value }),
    [dispatch],
  );

  const handleSubmitNeeds = useCallback(
    () => dispatch({ type: "submitNeeds" }),
    [dispatch],
  );

  if (!currentQuestion || !gaiaDone) return null;

  if (currentQuestion.fieldName === FIELD_NAMES.NEEDS) {
    return (
      <m.div {...MOTION_FADE_UP}>
        <OnboardingInput
          mode="needs"
          selectedNeeds={state.selectedNeeds}
          otherNeed={state.otherNeed}
          canContinue={canSubmitNeeds(state)}
          onToggleNeed={handleToggleNeed}
          onOtherNeedChange={handleOtherNeedChange}
          onContinue={handleSubmitNeeds}
        />
      </m.div>
    );
  }

  return (
    <m.div {...MOTION_FADE_UP}>
      <OnboardingInput
        mode="profession"
        draftProfession={draftProfession}
        onSelectProfession={handleSelectProfession}
        onContinue={handleSubmitProfession}
      />
    </m.div>
  );
}
