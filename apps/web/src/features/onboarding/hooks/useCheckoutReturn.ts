"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { usePricing } from "@/features/pricing/hooks/usePricing";
import { verifyPaymentWithRetry } from "@/features/pricing/utils/verifyPaymentWithRetry";

import { CHECKOUT_RETURNED_PARAM } from "../constants";

/** How long the wizard shows a plain "confirming" state before admitting the
 *  webhook is late. Polling continues underneath either way. */
const LATE_AFTER_MS = 30_000;

/** Dodo appends the subscription it just created to the return URL. */
const SUBSCRIPTION_ID_PARAM = "subscription_id";

interface CheckoutReturn {
  /** Dodo just sent the browser back to the wizard after checkout. */
  returned: boolean;
  /** Past the visible budget with no subscription yet. */
  isLate: boolean;
}

/**
 * A checkout started inside the wizard returns to `/onboarding?checkout=returned`
 * rather than the standalone result page, so the payment stage confirms the
 * charge in place. Two things make the subscription real on our side: the
 * webhook (polled by `useAwaitPaidStatus`) and, when that is late or lost, a
 * verify call that hands the server the subscription id off the return URL so
 * it can settle the question with Dodo directly. This hook runs the second,
 * times the wait, and clears the marker once the subscription is real so a
 * reload never replays the confirming state.
 */
export function useCheckoutReturn(): CheckoutReturn {
  const params = useSearchParams();
  const returned = params.get(CHECKOUT_RETURNED_PARAM) === "returned";
  const subscriptionId = params.get(SUBSCRIPTION_ID_PARAM) ?? undefined;
  const { isPaid } = useIsPaid();
  const { verifyPayment, refetchSubscription } = usePricing();
  const [isLate, setIsLate] = useState(false);
  const verifiedRef = useRef(false);

  useEffect(() => {
    if (!returned || isPaid || verifiedRef.current) return;
    verifiedRef.current = true;
    verifyPaymentWithRetry(() => verifyPayment(subscriptionId))
      .then(() => refetchSubscription())
      .catch((error: unknown) => {
        // The poll keeps going; a failed verify only loses the shortcut.
        console.error("Post-checkout verification failed:", error);
      });
  }, [returned, isPaid, subscriptionId, verifyPayment, refetchSubscription]);

  useEffect(() => {
    if (!returned || isPaid) return;
    const timer = setTimeout(() => setIsLate(true), LATE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [returned, isPaid]);

  // Not a redirect: the wizard stays put and only the marker leaves the URL,
  // so a later reload does not replay the confirming state.
  useEffect(() => {
    if (returned && isPaid)
      window.history.replaceState(null, "", "/onboarding");
  }, [returned, isPaid]);

  return { returned, isLate };
}
