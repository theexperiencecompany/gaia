/**
 * `payment` stage — the exclusive one. Nothing but a single framing bubble
 * and the priced tiers is on screen here; the page hides the transcript for
 * this stage so the decision has no competition.
 *
 * There is no composer and no skip: the stage ends when the backend reports
 * an active subscription. The checkout store's confirmation loop is what
 * waits for the webhook, on the overlay path and on Dodo's redirect back.
 */

"use client";

import { Spinner } from "@heroui/spinner";
import * as m from "motion/react-m";
import { useMemo, useState } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { firstNameOf } from "@/features/auth/utils/firstName";
import { BillingPeriodTabs } from "@/features/pricing/components/BillingPeriodTabs";
import { CheckoutConfirming } from "@/features/pricing/components/CheckoutConfirming";
import { CheckoutFailed } from "@/features/pricing/components/CheckoutFailed";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { paymentIntroLines } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import { useCheckoutReturn } from "../../hooks/useCheckoutReturn";
import { usePaceDone } from "../../hooks/useTypedLines";
import { OnboardingBotBubbles } from "../OnboardingBotBubbles";

const PAYMENT_REVEAL_KEY = "payment";

export function Payment() {
  const [isYearly, setIsYearly] = useState(false);
  const { isUnknown } = useIsPaid();
  const { returned, isLate, failed, timedOut, retry } = useCheckoutReturn();
  const gaiaDone = usePaceDone(PAYMENT_REVEAL_KEY);
  const { name, email } = useCurrentUser();
  const introLines = useMemo(
    () => paymentIntroLines(firstNameOf(name, email)),
    [name, email],
  );

  return (
    <m.div className="flex flex-col items-center gap-4" {...MOTION_FADE_UP}>
      <div className="w-full">
        <OnboardingBotBubbles
          lines={introLines}
          revealKey={PAYMENT_REVEAL_KEY}
        />
      </div>

      {/* Never render the cards off an unresolved plan status: a paying user
          would be shown an upgrade prompt they already bought. */}
      {isUnknown ? (
        <Spinner size="lg" aria-label="Checking your subscription" />
      ) : returned && (failed || timedOut) ? (
        // Declined, or nothing landed in two minutes: say so and hand the
        // plans back rather than spinning until the user gives up.
        <div className="w-full max-w-sm">
          <CheckoutFailed declined={failed} onRetry={retry} />
        </div>
      ) : returned ? (
        // Back from Dodo: the webhook makes the subscription real, and the
        // stage advances on its own the moment the poll sees it.
        <div className="w-full max-w-sm">
          <CheckoutConfirming isLate={isLate} />
        </div>
      ) : gaiaDone ? (
        // Scaled so the whole card sits on a laptop screen without scrolling;
        // `zoom` shrinks the layout box too, unlike a transform.
        <m.div
          className="flex w-full flex-col items-center gap-4 [zoom:0.85]"
          {...MOTION_FADE_UP}
        >
          <BillingPeriodTabs isYearly={isYearly} onChange={setIsYearly} />
          <PricingCards
            durationIsMonth={!isYearly}
            hideEnterprise
            checkoutSource="onboarding"
            hideHeader
          />
        </m.div>
      ) : null}
    </m.div>
  );
}
