/**
 * `paidReveal` stage. The receipt printer from the standalone result page,
 * printed in place: the stage is only reachable once the subscription status
 * has resolved to paid, so the receipt is built from that record and the
 * printer starts on the "printing" beat straight away.
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useEffect } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { PostPaymentReceipt } from "@/features/pricing/components/PostPaymentReceipt";
import { usePricing } from "@/features/pricing/hooks/usePricing";
import { useReceiptPrinterStage } from "@/features/pricing/hooks/useReceiptPrinterStage";
import { buildReceiptDetails } from "@/features/pricing/utils/receiptDetails";
import UseCreateConfetti from "@/hooks/ui/useCreateConfetti";
import { PAID_REVEAL_LINES } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingBotBubbles } from "../OnboardingMessages";

const CONFETTI_DURATION_MS = 3500;

export function PaidReveal() {
  const { subscriptionStatus } = usePricing();
  const user = useUser();
  const printerStage = useReceiptPrinterStage(true);
  const receipt = buildReceiptDetails(subscriptionStatus, undefined);

  useEffect(() => {
    const interval = UseCreateConfetti(CONFETTI_DURATION_MS);
    return () => {
      if (interval) clearInterval(interval);
    };
  }, []);

  return (
    <m.div className="flex flex-col items-center gap-6" {...MOTION_FADE_UP}>
      <div className="w-full">
        <OnboardingBotBubbles lines={PAID_REVEAL_LINES} />
      </div>
      <div className="w-full max-w-sm">
        <PostPaymentReceipt
          billingPeriod={receipt.billingPeriod}
          amount={receipt.amount}
          currency={receipt.currency}
          nextBillingDate={receipt.nextBillingDate}
          planName={receipt.planName}
          purchasedAt={receipt.purchasedAt}
          customerEmail={user.email || undefined}
          quantity={receipt.quantity}
          stage={printerStage}
          subscriptionRef={receipt.subscriptionRef}
        />
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
