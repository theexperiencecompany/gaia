/**
 * `greeting` stage. A single static bot bubble — no LLM call anywhere in
 * onboarding. Falls back to a name-less greeting when the user store has no
 * first name yet.
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useUserStore } from "@/stores/userStore";
import { greetingMessage } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingBotBubble } from "../OnboardingMessages";

export function Greeting() {
  const name = useUserStore((s) => s.name);
  const firstName = name?.trim().split(/\s+/)[0] || undefined;

  return (
    <m.div className="mt-4" {...MOTION_FADE_UP}>
      <OnboardingBotBubble text={greetingMessage(firstName)} />
    </m.div>
  );
}

export function GreetingComposer({ dispatch }: { dispatch: Dispatch<Action> }) {
  return (
    <ComposerCTA>
      <OnboardingCTAButton onClick={() => dispatch({ type: "ackGreeting" })}>
        Set me up
      </OnboardingCTAButton>
    </ComposerCTA>
  );
}
