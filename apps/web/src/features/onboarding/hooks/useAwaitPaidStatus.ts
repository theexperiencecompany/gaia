/**
 * Keeps the shared `["subscription-status"]` cache fresh while the user sits
 * on the payment stage. Dodo's webhook is what flips the subscription to
 * active, and it can land after the checkout overlay has already closed —
 * without a poll the flow would sit on the pricing cards of a plan the user
 * has already paid for.
 *
 * Stops itself as soon as the status resolves to paid.
 */

"use client";

import { useEffect } from "react";
import {
  useIsPaid,
  //
} from "@/features/pricing/hooks/useIsPaid";
import { usePricing } from "@/features/pricing/hooks/usePricing";

const POLL_INTERVAL_MS = 4000;

export function useAwaitPaidStatus(): void {
  const { isPaid } = useIsPaid();
  const { refetchSubscription } = usePricing();

  useEffect(() => {
    if (isPaid) return;
    const timer = setInterval(() => {
      void refetchSubscription();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isPaid, refetchSubscription]);
}
