"use client";

import { Button } from "@heroui/button";

import { CHECKOUT_DECLINED_COPY } from "../constants";

interface CheckoutFailedProps {
  /** Dodo reported the charge failed (vs. we simply never heard back). */
  declined: boolean;
  onRetry: () => void;
}

/** What replaces the confirming spinner when a checkout ends without a
 *  subscription: the card was declined, or nothing landed inside the budget. */
export function CheckoutFailed({ declined, onRetry }: CheckoutFailedProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-800/50 p-5 text-center">
      <p className="text-sm font-normal">
        {declined
          ? CHECKOUT_DECLINED_COPY.heading
          : "We couldn't confirm your payment."}
      </p>
      <p className="text-balance text-xs font-light text-zinc-400">
        {declined
          ? CHECKOUT_DECLINED_COPY.body
          : "If you were charged, everything unlocks the moment it lands. You can also just try again."}
      </p>
      <Button
        size="sm"
        color="primary"
        className="font-medium text-black"
        onPress={onRetry}
      >
        Try again
      </Button>
    </div>
  );
}
