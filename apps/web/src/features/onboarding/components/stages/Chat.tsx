/**
 * `chat` stage — the handoff. The click that confirmed the platform step
 * submitted onboarding; once the server confirms, the onboarding guard routes
 * the user into `/c`. A failed submit, or a resumed session that never sent
 * one, waits on the composer's button: nothing here submits on its own.
 */

"use client";

import { Spinner } from "@heroui/spinner";
import type { MutationStatus } from "@tanstack/react-query";
import * as m from "motion/react-m";
import {
  FINISH_CTA_LABEL,
  FINISH_FAILED_MESSAGE,
  FINISH_RETRY_LABEL,
  FINISHING_MESSAGE,
} from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { OnboardingSubmission } from "../../hooks/useOnboardingSubmission";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingBotBubble } from "../OnboardingBotBubble";
import { OnboardingCTAButton } from "../OnboardingCTAButton";

function isWaitingOnServer(status: MutationStatus): boolean {
  return status === "pending" || status === "success";
}

export function Chat({ status }: { status: MutationStatus }) {
  return (
    <m.div className="mt-4 flex flex-col gap-3" {...MOTION_FADE_UP}>
      <OnboardingBotBubble
        text={status === "error" ? FINISH_FAILED_MESSAGE : FINISHING_MESSAGE}
      />
      {isWaitingOnServer(status) && (
        <Spinner
          size="sm"
          className="sm:ml-10.75"
          aria-label="Finishing setup"
        />
      )}
    </m.div>
  );
}

export function ChatComposer({
  submission,
}: {
  submission: OnboardingSubmission;
}) {
  if (isWaitingOnServer(submission.status)) return null;
  return (
    <ComposerCTA>
      <OnboardingCTAButton onClick={submission.submit}>
        {submission.status === "error" ? FINISH_RETRY_LABEL : FINISH_CTA_LABEL}
      </OnboardingCTAButton>
    </ComposerCTA>
  );
}
