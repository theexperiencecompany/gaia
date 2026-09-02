"use client";

import { Button } from "@heroui/button";
import { RaisedButton } from "@/components/ui/raised-button";

import { REFUND_WINDOW_COPY, TAX_NOTE_COPY } from "../constants";
import { usePricingCardCta } from "../hooks/usePricingCardCta";
import type { PlanViewerState } from "../types";
import { CheckoutConfirming } from "./CheckoutConfirming";

interface PricingCardCtaProps {
  title: string;
  price: number;
  durationIsMonth: boolean;
  planId?: string;
  planViewerState: PlanViewerState;
}

export function PricingCardCta({
  title,
  price,
  durationIsMonth,
  planId,
  planViewerState,
}: PricingCardCtaProps) {
  const {
    buttonText,
    isCtaDisabled,
    isConfirmingPayment,
    isCheckoutLate,
    paymentError,
    isFree,
    isOnFreePlan,
    onGetStarted,
  } = usePricingCardCta({
    title,
    price,
    durationIsMonth,
    planId,
    planViewerState,
  });

  return (
    <div className="px-6 pb-5">
      {paymentError && (
        <div className="mb-3 rounded-xl bg-red-500/10 p-3">
          <p className="text-sm text-red-400">{paymentError}</p>
        </div>
      )}
      {isFree ? (
        <FreePlanCta isOnFreePlan={isOnFreePlan} onGetStarted={onGetStarted} />
      ) : (
        <PaidPlanCta
          buttonText={buttonText}
          isCtaDisabled={isCtaDisabled}
          isCheckoutLate={isCheckoutLate}
          isConfirmingPayment={isConfirmingPayment}
          onGetStarted={onGetStarted}
        />
      )}
    </div>
  );
}

interface PaidPlanCtaProps {
  buttonText: string;
  isCtaDisabled: boolean;
  isCheckoutLate: boolean;
  isConfirmingPayment: boolean;
  onGetStarted: () => void;
}

function PaidPlanCta({
  buttonText,
  isCtaDisabled,
  isCheckoutLate,
  isConfirmingPayment,
  onGetStarted,
}: PaidPlanCtaProps) {
  if (isConfirmingPayment)
    return <CheckoutConfirming isLate={isCheckoutLate} />;
  return (
    <>
      <RaisedButton
        className="w-full text-black!"
        color="#00bbff"
        onClick={onGetStarted}
        disabled={isCtaDisabled}
      >
        {buttonText}
      </RaisedButton>
      <p className="mt-2 text-center text-xs font-light text-zinc-500">
        {REFUND_WINDOW_COPY} {TAX_NOTE_COPY}
      </p>
    </>
  );
}

interface FreePlanCtaProps {
  isOnFreePlan: boolean;
  onGetStarted: () => void;
}

// GAIA is paid-only: the backend no longer serves a $0 plan (PricingCards
// filters any stray $0 row out before it reaches this component), so this
// branch is effectively unreachable. Kept as a defensive fallback.
function FreePlanCta({ isOnFreePlan, onGetStarted }: FreePlanCtaProps) {
  if (isOnFreePlan)
    return (
      <Button isDisabled className="w-full" variant="flat">
        Current Plan
      </Button>
    );
  return (
    <Button className="w-full" variant="flat" onPress={onGetStarted}>
      Start for Free
    </Button>
  );
}
