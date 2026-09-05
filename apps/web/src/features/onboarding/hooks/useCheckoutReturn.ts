"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { usePricing } from "@/features/pricing/hooks/usePricing";
import { verifyPaymentWithRetry } from "@/features/pricing/utils/verifyPaymentWithRetry";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

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
 * times the wait, and reads a failed outcome straight off the URL. The query
 * is consumed on first render and removed from the address bar immediately.
 */
interface ReturnParams {
  returned: boolean;
  failed: boolean;
  subscriptionId?: string;
}

const NOT_RETURNED: ReturnParams = { returned: false, failed: false };

function readReturnParams(params: URLSearchParams): ReturnParams {
  const returned = params.get(CHECKOUT_RETURNED_PARAM) === "returned";
  if (!returned) return NOT_RETURNED;
  return {
    returned,
    failed: params.get(STATUS_PARAM) === "failed",
    subscriptionId: params.get(SUBSCRIPTION_ID_PARAM) ?? undefined,
  };
}

const CLEAN_PATH = "/onboarding";

export function useCheckoutReturn(): CheckoutReturn {
  const searchParams = useSearchParams();
  // Read Dodo's query once, into state, then strip it from the URL right
  // away: the outcome lives here for the rest of the visit, and nothing that
  // reloads, shares or bookmarks the page can replay a stale checkout.
  const [{ returned, failed, subscriptionId }, setReturnParams] = useState(() =>
    readReturnParams(new URLSearchParams(searchParams.toString())),
  );
  useEffect(() => {
    if (window.location.search)
      window.history.replaceState(null, "", CLEAN_PATH);
  }, []);
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

  // A checkout that never became a subscription is invisible to the server:
  // a declined charge produces no webhook, and a webhook that never lands
  // produces nothing at all. Only the browser sees either outcome.
  const outcomeTrackedRef = useRef(false);
  useEffect(() => {
    if (!returned || outcomeTrackedRef.current) return;
    if (!failed && !timedOut) return;
    outcomeTrackedRef.current = true;
    trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_FAILED, {
      source: "onboarding",
      reason: failed ? "declined" : "confirmation_timeout",
    });
  }, [returned, failed, timedOut]);

  const retry = () => {
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_CHECKOUT_RETRIED, {
      reason: failed ? "declined" : "confirmation_timeout",
    });
    outcomeTrackedRef.current = false;
    setIsLate(false);
    setTimedOut(false);
    verifiedRef.current = false;
    setReturnParams(NOT_RETURNED);
  };

  return { returned, isLate, failed, timedOut, retry };
}
