/**
 * Top-level orchestrator page for the onboarding flow. Uses `useOnboarding`
 * to get the derived stage, then picks a `stageContent` and a `composer`
 * for that stage. Stage-driven swapping keeps each stage's logic isolated;
 * shared transcript + progress chrome live in `OnboardingShell` /
 * `MessagesRegion`. `skipAutoRedirect` keeps the chat stage rendered here
 * instead of redirecting into the standalone `/c/:id` route.
 */

"use client";

import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { CompletedStagesTimeline } from "@/features/onboarding/components/CompletedStagesTimeline";
import { MessagesRegion } from "@/features/onboarding/components/MessagesRegion";
import { OnboardingIntro } from "@/features/onboarding/components/OnboardingIntro";
import { OnboardingShell } from "@/features/onboarding/components/OnboardingShell";
import {
  Chat,
  ChatComposer,
  ClarifyComposer,
  FocusComposer,
  Platforms,
  PlatformsComposer,
  QuestionsComposer,
  RevealTodos,
  RevealTodosComposer,
  RevealWritingStyle,
  RevealWritingStyleComposer,
  useChatStage,
  Workflows,
  WorkflowsComposer,
} from "@/features/onboarding/components/stages";
import { EASE_OUT_QUART } from "@/features/onboarding/constants/motion";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";
import { useUserStore } from "@/stores/userStore";

const INTRO_FADE_IN = {
  initial: { opacity: 0, filter: "blur(12px)" },
  animate: { opacity: 1, filter: "blur(0px)" },
  transition: { duration: 0.6, ease: EASE_OUT_QUART },
} as const;

const INTRO_SEEN_PREFIX = "gaia.onboarding.introSeen";

function introSeenKey(userId: string): string | null {
  return userId ? `${INTRO_SEEN_PREFIX}.${userId}` : null;
}

function hasSeenIntro(userId: string): boolean {
  if (typeof window === "undefined") return false;
  const key = introSeenKey(userId);
  if (!key) return false;
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function markIntroSeen(userId: string): void {
  const key = introSeenKey(userId);
  if (!key) return;
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // localStorage unavailable (private mode, etc.) — silently skip.
  }
}

function clearIntroSeen(userId: string): void {
  const key = introSeenKey(userId);
  if (!key) return;
  try {
    window.localStorage.removeItem(key);
  } catch {}
}

export default function Onboarding() {
  const { state, stage, dispatch, restart } = useOnboarding({
    skipAutoRedirect: true,
  });
  const userId = useUserStore((s) => s.userId);
  // `null` until userId hydrates from persisted storage, so the intro doesn't replay on every reload.
  const [introDone, setIntroDone] = useState<boolean | null>(() =>
    userId ? hasSeenIntro(userId) : null,
  );

  useEffect(() => {
    if (!userId) return;
    setIntroDone((prev) => (prev === null ? hasSeenIntro(userId) : prev));
  }, [userId]);

  const handleRestart = () => {
    clearIntroSeen(userId);
    setIntroDone(false);
    return restart();
  };

  const handleIntroComplete = () => {
    markIntroSeen(userId);
    setIntroDone(true);
  };

  const { welcome: welcomeChat, todoDemo: todoDemoChat } = useChatStage(
    state,
    dispatch,
  );

  const stageContent = (() => {
    switch (stage) {
      case "questions":
      case "focus":
      case "clarify":
      case "processing":
        return null;
      case "revealWriting":
        return <RevealWritingStyle state={state} />;
      case "revealTodos":
        return (
          <RevealTodos state={state} dispatch={dispatch} chat={todoDemoChat} />
        );
      case "workflows":
        return <Workflows state={state} dispatch={dispatch} />;
      case "platforms":
        return <Platforms state={state} dispatch={dispatch} />;
      case "chat":
        return <Chat state={state} />;
    }
  })();

  const composer = (() => {
    switch (stage) {
      case "questions":
        return <QuestionsComposer state={state} dispatch={dispatch} />;
      case "focus":
        return <FocusComposer state={state} dispatch={dispatch} />;
      case "clarify":
        return <ClarifyComposer state={state} dispatch={dispatch} />;
      case "processing":
        return null;
      case "revealWriting":
        return <RevealWritingStyleComposer state={state} dispatch={dispatch} />;
      case "revealTodos":
        return <RevealTodosComposer dispatch={dispatch} chat={todoDemoChat} />;
      case "workflows":
        return <WorkflowsComposer state={state} dispatch={dispatch} />;
      case "platforms":
        return <PlatformsComposer state={state} dispatch={dispatch} />;
      case "chat":
        return <ChatComposer state={state} />;
    }
  })();

  const wrappedComposer = introDone ? (
    <m.div {...INTRO_FADE_IN}>{composer}</m.div>
  ) : null;

  const introResolved = introDone !== null;

  return (
    <>
      <OnboardingShell
        state={state}
        stage={stage}
        onRestart={handleRestart}
        composer={wrappedComposer}
      >
        {introDone ? (
          <m.div {...INTRO_FADE_IN}>
            <MessagesRegion state={state} stage={stage} />
            <CompletedStagesTimeline
              state={state}
              dispatch={dispatch}
              chat={todoDemoChat}
            />
            {stageContent}
          </m.div>
        ) : null}
      </OnboardingShell>
      <AnimatePresence>
        {introResolved && !introDone && (
          <OnboardingIntro onComplete={handleIntroComplete} />
        )}
      </AnimatePresence>
    </>
  );
}
