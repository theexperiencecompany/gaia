/**
 * Top-level orchestrator page for the onboarding flow. Uses `useOnboarding`
 * to get the derived stage, then picks a `stageContent` and a `composer`
 * for that stage. Stage-driven swapping keeps each stage's logic isolated;
 * shared transcript + progress chrome live in `OnboardingShell` /
 * `MessagesRegion`.
 *
 * Only the `questions` stage shows the Q&A transcript. From `payment` on the
 * screen is exclusive to that stage: nothing competes with the decision, the
 * receipt prints at the top instead of below a scroll of bubbles, and the
 * platform pick opens on its own bubbles rather than the answered questions.
 */

"use client";

import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { MessagesRegion } from "@/features/onboarding/components/MessagesRegion";
import { OnboardingIntro } from "@/features/onboarding/components/OnboardingIntro";
import { OnboardingShell } from "@/features/onboarding/components/OnboardingShell";
import {
  Chat,
  PaidReveal,
  PaidRevealComposer,
  Payment,
  Platforms,
  QuestionsReply,
} from "@/features/onboarding/components/stages";
import { EASE_OUT_QUART } from "@/features/onboarding/constants/motion";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";

const INTRO_FADE_IN = {
  initial: { opacity: 0, filter: "blur(12px)" },
  animate: { opacity: 1, filter: "blur(0px)" },
  transition: { duration: 0.6, ease: EASE_OUT_QUART },
} as const;

export default function Onboarding() {
  // `introSeen` is owned by the onboarding state (persisted alongside the rest
  // of the wizard's progress) and is `null` until storage has been read, so
  // server and first client render agree and the intro never replays.
  const { state, stage, dispatch, introSeen, markIntroSeen, restart } =
    useOnboarding();
  const introDone = introSeen === true;

  const stageContent = (() => {
    switch (stage) {
      case "questions":
        return <QuestionsReply state={state} dispatch={dispatch} />;
      case "payment":
        return <Payment />;
      case "paidReveal":
        return <PaidReveal />;
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
      case "platformPick":
      case "chat":
        return null;
      case "paidReveal":
        return <PaidRevealComposer dispatch={dispatch} />;
    }
  })();

  const wrappedComposer = introDone ? (
    <m.div {...INTRO_FADE_IN}>{composer}</m.div>
  ) : null;

  const introResolved = introSeen !== null;

  return (
    <>
      <OnboardingShell
        state={state}
        stage={stage}
        onRestart={restart}
        composer={wrappedComposer}
      >
        {introDone ? (
          <m.div {...INTRO_FADE_IN}>
            {/* Past payment the Q&A is history: the platform step stands on
                its own bubbles, and the receipt on its confetti. */}
            {stage === "questions" && <MessagesRegion state={state} />}
            {stageContent}
          </m.div>
        ) : null}
      </OnboardingShell>
      <AnimatePresence>
        {introResolved && !introDone && (
          <OnboardingIntro onComplete={markIntroSeen} />
        )}
      </AnimatePresence>
    </>
  );
}
