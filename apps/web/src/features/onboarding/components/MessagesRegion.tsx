/**
 * Renders the Q&A transcript at the top of the page for stages that build
 * on it (questions / focus / processing / writing-style reveal / todos
 * reveal). Mounted once at the page level so the message list isn't
 * remounted on every stage transition. For pipeline stages, also nests
 * the `OnboardingProcessing` checklist inside the last bot bubble.
 */

"use client";

import { memo, useMemo } from "react";
import { hasGmail as hasGmailDerived } from "../state/derive";
import { getMessages } from "../state/messages";
import type { OnboardingState, Stage } from "../state/types";
import { OnboardingMessages } from "./OnboardingMessages";
import { OnboardingProcessing } from "./OnboardingProcessing";

const STAGES_WITH_PROCESSING_CHECKLIST: ReadonlySet<Stage> = new Set<Stage>([
  "processing",
  "revealWriting",
  "revealTodos",
  "workflows",
  "platforms",
  "chat",
]);

interface MessagesRegionProps {
  state: OnboardingState;
  stage: Stage;
}

function MessagesRegionImpl({ state, stage }: MessagesRegionProps) {
  const messages = useMemo(
    () => getMessages(state),
    [
      state.responses,
      state.questionIndex,
      state.clarifyAnswers,
      state.clarifyQuestions,
      state.clarifySubmitted,
    ],
  );

  const checklist = STAGES_WITH_PROCESSING_CHECKLIST.has(stage) ? (
    <OnboardingProcessing
      hasGmail={hasGmailDerived(state)}
      completedStages={state.completedStages}
      progressByStage={state.progressByStage}
    />
  ) : null;

  return (
    <OnboardingMessages messages={messages} processingChecklist={checklist} />
  );
}

export const MessagesRegion = memo(MessagesRegionImpl);
