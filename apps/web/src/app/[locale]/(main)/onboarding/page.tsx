/**
 * Top-level orchestrator page for the onboarding flow. Uses `useOnboarding`
 * to get the derived stage, then picks a `stageContent` and a `composer`
 * for that stage. Stage-driven swapping keeps each stage's logic isolated;
 * shared transcript + progress chrome live in `OnboardingShell` /
 * `MessagesRegion`. `skipAutoRedirect` keeps the chat stage rendered here
 * instead of redirecting into the standalone `/c/:id` route.
 */

"use client";

import { MessagesRegion } from "@/features/onboarding/components/MessagesRegion";
import { OnboardingShell } from "@/features/onboarding/components/OnboardingShell";
import {
  Chat,
  ChatComposer,
  FocusComposer,
  Platforms,
  ProcessingComposer,
  QuestionsComposer,
  RevealTodos,
  RevealWritingStyle,
  RevealWritingStyleComposer,
  useChatStage,
  Workflows,
  WorkflowsComposer,
} from "@/features/onboarding/components/stages";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";

export default function Onboarding() {
  const { state, stage, dispatch, restart } = useOnboarding({
    skipAutoRedirect: true,
  });

  const chat = useChatStage(state, dispatch);

  const stageContent = (() => {
    switch (stage) {
      case "questions":
      case "focus":
      case "processing":
        return null;
      case "revealWriting":
        return <RevealWritingStyle state={state} />;
      case "revealTodos":
        return <RevealTodos state={state} dispatch={dispatch} />;
      case "workflows":
        return <Workflows state={state} dispatch={dispatch} />;
      case "platforms":
        return <Platforms state={state} dispatch={dispatch} />;
      case "chat":
        return <Chat state={state} chat={chat} />;
    }
  })();

  const composer = (() => {
    switch (stage) {
      case "questions":
        return <QuestionsComposer state={state} dispatch={dispatch} />;
      case "focus":
        return <FocusComposer state={state} dispatch={dispatch} />;
      case "processing":
        return <ProcessingComposer state={state} dispatch={dispatch} />;
      case "revealWriting":
        return <RevealWritingStyleComposer state={state} dispatch={dispatch} />;
      case "revealTodos":
        return null;
      case "workflows":
        return <WorkflowsComposer state={state} dispatch={dispatch} />;
      case "platforms":
        return null;
      case "chat":
        return <ChatComposer chat={chat} />;
    }
  })();

  return (
    <OnboardingShell
      state={state}
      stage={stage}
      onRestart={restart}
      composer={composer}
    >
      <MessagesRegion state={state} stage={stage} />
      {stageContent}
    </OnboardingShell>
  );
}
