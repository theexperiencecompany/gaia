/**
 * `paidReveal` stage. The payment-success card, celebrated with the same
 * confetti the standalone `/payment/success` page fires. No verification
 * call here: the stage is only reachable once the subscription status has
 * already resolved to paid, which is the same fact `verifyPayment` returns.
 */

"use client";

import { CheckmarkCircle02Icon } from "@icons";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useEffect } from "react";
import UseCreateConfetti from "@/hooks/ui/useCreateConfetti";
import { PAID_REVEAL_BODY, PAID_REVEAL_TITLE } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";

const CONFETTI_DURATION_MS = 3500;

export function PaidReveal() {
  useEffect(() => {
    const interval = UseCreateConfetti(CONFETTI_DURATION_MS);
    return () => {
      if (interval) clearInterval(interval);
    };
  }, []);

  return (
    <m.div className="flex justify-center" {...MOTION_FADE_UP}>
      <div className="w-full max-w-md rounded-3xl bg-zinc-900/60 p-8 text-center backdrop-blur-2xl">
        <CheckmarkCircle02Icon className="mx-auto mb-5 size-16 text-primary" />
        <h2 className="mb-2 font-semibold text-2xl text-white">
          {PAID_REVEAL_TITLE}
        </h2>
        <p className="text-balance font-light text-sm text-zinc-400">
          {PAID_REVEAL_BODY}
        </p>
      </div>
    </m.div>
  );
}

export function PaidRevealComposer({
  dispatch,
}: {
  dispatch: Dispatch<Action>;
}) {
  return (
    <ComposerCTA>
      <OnboardingCTAButton onClick={() => dispatch({ type: "ackPaidReveal" })}>
        Let's go
      </OnboardingCTAButton>
    </ComposerCTA>
  );
}
