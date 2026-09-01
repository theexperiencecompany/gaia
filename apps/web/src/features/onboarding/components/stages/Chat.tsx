/**
 * `chat` stage — the handoff. Reaching it is what submits onboarding
 * (`useOnboardingSubmission`); once the server confirms, the onboarding
 * guard routes the user into `/c`. Nothing is seeded here: composing and
 * injecting the first message is Phase 7's job.
 */

"use client";

import { Spinner } from "@heroui/spinner";
import * as m from "motion/react-m";
import { FINISHING_MESSAGE } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import { OnboardingBotBubble } from "../OnboardingMessages";

export function Chat() {
  return (
    <m.div className="mt-4 flex flex-col gap-3" {...MOTION_FADE_UP}>
      <OnboardingBotBubble text={FINISHING_MESSAGE} />
      <Spinner size="sm" className="ml-10.75" aria-label="Finishing setup" />
    </m.div>
  );
}
