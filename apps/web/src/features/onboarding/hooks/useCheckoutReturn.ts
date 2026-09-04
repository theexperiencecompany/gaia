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
/** Past this with still no subscription, stop spinning and offer a retry. A
 *  charge that lands later still unlocks access: the poll never stops. */
const GIVE_UP_AFTER_MS = 120_000;
/** Dodo appends the subscription it just created to the return URL. */
const SUBSCRIPTION_ID_PARAM = "subscription_id";
/** ...and the outcome of the charge: `succeeded`, `failed`, `processing`. */
const STATUS_PARAM = "status";

interface CheckoutReturn {
  /** Dodo just sent the browser back to the wizard after checkout. */
  returned: boolean;
  /** Past the visible budget with no subscription yet. */
  isLate: boolean;
  /** Dodo said the charge failed: nothing to wait for, offer a retry. */
  failed: boolean;
  /** Waited the whole budget and nothing landed. */
  timedOut: boolean;
  /** Leave the confirming state and show the plans again. */
  retry: () => void;
}

/**
 * A checkout started inside the wizard returns to `/onboarding?checkout=returned`
 * rather than the standalone result page, so the payment stage confirms the
 * charge in place. Two things make the subscription real on our side: the
 * webhook (polled by `useAwaitPaidStatus`) and, when that is late or lost, a
 * verify call that hands the server the subscription id off the return URL so
 * it can settle the question with Dodo directly. This hook runs the second,
 * times the wait, reads a failed outcome straight off the URL, and clears the
 * marker once the subscription is real so a reload never replays the
 * confirming state.
 */
export function useCheckoutReturn(): CheckoutReturn {
  const params = useSearchParams();
  const returned = params.get(CHECKOUT_RETURNED_PARAM) === "returned";
  const failed = returned && params.get(STATUS_PARAM) === "failed";
  const subscriptionId = params.get(SUBSCRIPTION_ID_PARAM) ?? undefined;
  const { isPaid } = useIsPaid();
  const { verifyPayment, refetchSubscription } = usePricing();
  const [isLate, setIsLate] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const verifiedRef = useRef(false);

  const waiting = returned && !failed && !isPaid;

  useEffect(() => {
    if (!waiting || verifiedRef.current) return;
    verifiedRef.current = true;
    verifyPaymentWithRetry(() => verifyPayment(subscriptionId))
      .then(() => refetchSubscription())
      .catch((error: unknown) => {
        // The poll keeps going; a failed verify only loses the shortcut.
        console.error("Post-checkout verification failed:", error);
      });
  }, [waiting, subscriptionId, verifyPayment, refetchSubscription]);

  useEffect(() => {
    if (!waiting) return;
    const late = setTimeout(() => setIsLate(true), LATE_AFTER_MS);
    const giveUp = setTimeout(() => setTimedOut(true), GIVE_UP_AFTER_MS);
    return () => {
      clearTimeout(late);
      clearTimeout(giveUp);
    };
  }, [waiting]);

  // Not a redirect: the wizard stays put and only the marker leaves the URL,
  // so a later reload does not replay the confirming state.
  useEffect(() => {
    if (returned && isPaid)
      window.history.replaceState(null, "", "/onboarding");
  }, [returned, isPaid]);

  const retry = () => {
    setIsLate(false);
    setTimedOut(false);
    verifiedRef.current = false;
    window.history.replaceState(null, "", "/onboarding");
  };

  return { returned, isLate, failed, timedOut, retry };
}
