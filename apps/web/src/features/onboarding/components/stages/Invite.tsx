/**
 * `invite` stage. Straight after the receipt, the new subscriber gets their
 * gift link while the purchase is fresh; continuing never depends on sharing.
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { OnboardingReferral } from "@/features/referrals/components/PostPaymentShareCard";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";

export function Invite() {
  return (
    <m.div className="flex flex-col items-center" {...MOTION_FADE_UP}>
      <div className="w-full max-w-sm">
        <OnboardingReferral />
      </div>
    </m.div>
  );
}

export function InviteComposer({ dispatch }: { dispatch: Dispatch<Action> }) {
  return (
    <ComposerCTA>
      <OnboardingCTAButton onClick={() => dispatch({ type: "ackInvite" })}>
        Continue
      </OnboardingCTAButton>
    </ComposerCTA>
  );
}
