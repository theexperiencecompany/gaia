/**
 * `questions` stage. Active until Q1 (profession), Q2 (needs) and Q3 (where
 * they heard of GAIA) are answered and stored. The transcript renders in `MessagesRegion`; this file
 * owns the user's reply to the active question, rendered in the thread on
 * their side, and the save that follows the last one.
 */

"use client";

import { Spinner } from "@heroui/react";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useCallback } from "react";
import { FIELD_NAMES, isKnownNeed, questions } from "../../constants";
import {
  ANSWERS_SAVE_FAILED_MESSAGE,
  ANSWERS_SAVING_LABEL,
  FINISH_RETRY_LABEL,
} from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { AnswersSave } from "../../effects/useOnboardingPreferences";
import { usePaceDone } from "../../hooks/useTypedLines";
import { canSubmitNeeds, isAtNeedsCap } from "../../state/derive";
import { questionRevealKey } from "../../state/paceStore";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingBotBubble } from "../OnboardingBotBubble";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingInput } from "../OnboardingInput";

interface QuestionsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  answersSave: AnswersSave;
}

function AnswersSaveStatus({ answersSave }: { answersSave: AnswersSave }) {
  if (answersSave.status === "error") {
    return (
      <m.div className="flex flex-col items-start gap-3" {...MOTION_FADE_UP}>
        <OnboardingBotBubble lines={[ANSWERS_SAVE_FAILED_MESSAGE]} />
        <OnboardingCTAButton
          className="sm:ml-10.75"
          onClick={answersSave.retry}
        >
          {FINISH_RETRY_LABEL}
        </OnboardingCTAButton>
      </m.div>
    );
  }
  return (
    <Spinner
      size="sm"
      className="sm:ml-10.75"
      aria-label={ANSWERS_SAVING_LABEL}
    />
  );
}

export function QuestionsReply({
  state,
  dispatch,
  answersSave,
}: QuestionsProps) {
  const currentQuestion = questions[state.questionIndex];
  // The reply only shows up once GAIA has finished "typing" the question.
  const gaiaDone = usePaceDone(questionRevealKey(currentQuestion?.id ?? ""));

  const handleSelectChoice = useCallback(
    (value: string) => dispatch({ type: "draftChoice", value }),
    [dispatch],
  );

  const { draftChoice } = state;
  const fieldName = currentQuestion?.fieldName;
  const handleSubmitChoice = useCallback(() => {
    if (!draftChoice || !fieldName) return;
    dispatch({ type: "answer", field: fieldName, value: draftChoice });
  }, [dispatch, draftChoice, fieldName]);

  const handleToggleNeed = useCallback(
    (value: string) => {
      if (isKnownNeed(value)) dispatch({ type: "toggleNeed", value });
    },
    [dispatch],
  );

  const handleToggleOtherNeed = useCallback(
    () => dispatch({ type: "toggleOtherNeed" }),
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

  if (!currentQuestion) return <AnswersSaveStatus answersSave={answersSave} />;
  if (!gaiaDone) return null;

  if (currentQuestion.fieldName === FIELD_NAMES.NEEDS) {
    return (
      <m.div {...MOTION_FADE_UP}>
        <OnboardingInput
          mode="needs"
          profession={state.responses[FIELD_NAMES.PROFESSION] ?? null}
          selectedNeeds={state.selectedNeeds}
          otherNeed={state.otherNeed}
          otherOpen={state.otherNeedOpen}
          atCap={isAtNeedsCap(state)}
          canContinue={canSubmitNeeds(state)}
          onToggleNeed={handleToggleNeed}
          onToggleOtherNeed={handleToggleOtherNeed}
          onOtherNeedChange={handleOtherNeedChange}
          onContinue={handleSubmitNeeds}
        />
      </m.div>
    );
  }

  if (currentQuestion.fieldName === FIELD_NAMES.HEARD_FROM) {
    return (
      <m.div {...MOTION_FADE_UP}>
        <OnboardingInput
          mode="heardFrom"
          draftChoice={draftChoice}
          onSelect={handleSelectChoice}
          onContinue={handleSubmitChoice}
        />
      </m.div>
    );
  }

  return (
    <m.div {...MOTION_FADE_UP}>
      <OnboardingInput
        mode="profession"
        draftChoice={draftChoice}
        onSelectProfession={handleSelectChoice}
        onContinue={handleSubmitChoice}
      />
    </m.div>
  );
}
