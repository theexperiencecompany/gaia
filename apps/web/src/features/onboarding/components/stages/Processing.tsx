/**
 * `processing` stage. The visible checklist itself lives in `MessagesRegion`
 * (rendered above this composer); this file only owns the retry composer
 * shown when `submissionError` is true.
 */

"use client";

import { Button } from "@heroui/button";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { RETRY_LABEL, SUBMISSION_ERROR_MSG } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action, OnboardingState } from "../../state/types";

interface ProcessingProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

/** Renders the retry button only when `submissionError` is set. */
export function ProcessingComposer({ state, dispatch }: ProcessingProps) {
  if (!state.submissionError) return null;
  return (
    <m.div
      className="flex flex-col items-center gap-2 px-4"
      {...MOTION_FADE_UP}
    >
      <p className="text-sm text-zinc-400">{SUBMISSION_ERROR_MSG}</p>
      <Button
        size="sm"
        variant="flat"
        onPress={() => dispatch({ type: "retrySubmit" })}
      >
        {RETRY_LABEL}
      </Button>
    </m.div>
  );
}
