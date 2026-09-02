/**
 * `payment` stage — the exclusive one. Nothing but a single framing bubble
 * and the priced tiers is on screen here; the page hides the transcript for
 * this stage so the decision has no competition.
 *
 * There is no composer and no skip: the stage ends when the backend reports
 * an active subscription, which `useAwaitPaidStatus` polls for so a webhook
 * that lands after the checkout overlay closes still advances the flow.
 */

"use client";

import { Spinner } from "@heroui/spinner";
import * as m from "motion/react-m";
import { useState } from "react";
import { BillingPeriodTabs } from "@/features/pricing/components/BillingPeriodTabs";
import { CheckoutConfirming } from "@/features/pricing/components/CheckoutConfirming";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { PAYMENT_INTRO_LINES } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import { useAwaitPaidStatus } from "../../hooks/useAwaitPaidStatus";
import { useCheckoutReturn } from "../../hooks/useCheckoutReturn";
import { OnboardingBotBubbles } from "../OnboardingBotBubbles";

export function Payment() {
  const [isYearly, setIsYearly] = useState(false);
  const { isUnknown } = useIsPaid();
  const { returned, isLate } = useCheckoutReturn();
  useAwaitPaidStatus();

  return (
    <m.div className="flex flex-col items-center gap-4" {...MOTION_FADE_UP}>
      <div className="w-full">
        <OnboardingBotBubbles lines={PAYMENT_INTRO_LINES} />
      </div>

      {/* Never render the cards off an unresolved plan status: a paying user
          would be shown an upgrade prompt they already bought. */}
      {isUnknown ? (
        <Spinner size="lg" aria-label="Checking your subscription" />
      ) : returned ? (
        // Back from Dodo: the webhook makes the subscription real, and the
        // stage advances on its own the moment the poll sees it.
        <div className="w-full max-w-sm">
          <CheckoutConfirming isLate={isLate} />
        </div>
      ) : (
        // Scaled so the whole card sits on a laptop screen without scrolling;
        // `zoom` shrinks the layout box too, unlike a transform.
        <div className="flex w-full flex-col items-center gap-4 [zoom:0.85]">
          <BillingPeriodTabs isYearly={isYearly} onChange={setIsYearly} />
          <PricingCards
            durationIsMonth={!isYearly}
            hideEnterprise
            checkoutSource="onboarding"
            hideHeader
          />
        </div>
      )}
    </m.div>
  );
}
