"use client";

import { RaisedButton } from "@/components/ui/raised-button";

import type { CheckoutSource } from "../api/pricingApi";
import { usePricingCardCta } from "../hooks/usePricingCardCta";
import type { PlanViewerState } from "../types";
import { CheckoutConfirming } from "./CheckoutConfirming";

interface PricingCardCtaProps {
  title: string;
  price: number;
  durationIsMonth: boolean;
  planId?: string;
  planViewerState: PlanViewerState;
  checkoutSource?: CheckoutSource;
}

export function PricingCardCta({
  title,
  price,
  durationIsMonth,
  planId,
  planViewerState,
  checkoutSource,
}: PricingCardCtaProps) {
  const {
    buttonText,
    isCtaDisabled,
    isConfirmingPayment,
    isCheckoutLate,
    paymentError,
    onGetStarted,
  } = usePricingCardCta({
    title,
    price,
    durationIsMonth,
    planId,
    planViewerState,
    checkoutSource,
  });

  return (
    <div className="px-6 pb-4">
      {paymentError && (
        <div className="mb-3 rounded-xl bg-red-500/10 p-3">
          <p className="text-sm text-red-400">{paymentError}</p>
        </div>
      )}
      <PaidPlanCta
        buttonText={buttonText}
        isCtaDisabled={isCtaDisabled}
        isCheckoutLate={isCheckoutLate}
        isConfirmingPayment={isConfirmingPayment}
        onGetStarted={onGetStarted}
      />
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
    <RaisedButton
      className="w-full text-black!"
      color="#00bbff"
      onClick={onGetStarted}
      disabled={isCtaDisabled}
    >
      {buttonText}
    </RaisedButton>
  );
}
