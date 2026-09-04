/**
 * Top-level orchestrator page for the onboarding flow. Uses `useOnboarding`
 * to get the derived stage, then picks a `stageContent` and a `composer`
 * for that stage. Stage-driven swapping keeps each stage's logic isolated;
 * shared transcript + progress chrome live in `OnboardingShell` /
 * `MessagesRegion`.
 *
 * The `payment` and `paidReveal` stages are deliberately exclusive: the
 * transcript is hidden so nothing competes with the decision, and the receipt
 * prints at the top of the screen instead of below a scroll of bubbles.
 */

"use client";

import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { MessagesRegion } from "@/features/onboarding/components/MessagesRegion";
import { OnboardingIntro } from "@/features/onboarding/components/OnboardingIntro";
import { OnboardingShell } from "@/features/onboarding/components/OnboardingShell";
import {
  Chat,
  Greeting,
  GreetingComposer,
  PaidReveal,
  PaidRevealComposer,
  Payment,
  Platforms,
  PlatformsComposer,
  QuestionsReply,
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
  } catch {
    // localStorage unavailable (private mode, etc.) — silently skip.
  }
}

export default function Onboarding() {
  const { state, stage, dispatch, restart } = useOnboarding();
  const userId = useUserStore((s) => s.userId);
  // `null` until userId hydrates from persisted storage AND we confirm on the
  // client, so the intro doesn't replay on every reload and server/client
  // render identically (no hydration mismatch).
  const [introDone, setIntroDone] = useState<boolean | null>(null);

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

  const stageContent = (() => {
    switch (stage) {
      case "questions":
        return <QuestionsReply state={state} dispatch={dispatch} />;
      case "payment":
        return <Payment />;
      case "paidReveal":
        return <PaidReveal />;
      case "greeting":
        return <Greeting />;
      case "platformPick":
        return <Platforms state={state} dispatch={dispatch} />;
      case "chat":
        return <Chat />;
    }
  })();

  const composer = (() => {
    switch (stage) {
      case "questions":
      case "payment":
      case "chat":
        return null;
      case "paidReveal":
        return <PaidRevealComposer dispatch={dispatch} />;
      case "greeting":
        return <GreetingComposer dispatch={dispatch} />;
      case "platformPick":
        return <PlatformsComposer state={state} dispatch={dispatch} />;
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
            {stage !== "payment" && stage !== "paidReveal" && (
              <MessagesRegion state={state} />
            )}
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
