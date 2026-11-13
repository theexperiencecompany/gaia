"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useDodoPayments } from "@/features/pricing/hooks/useDodoPayments";
import {
  DODO_RETURN_PARAM,
  stripCheckoutReturnParams,
} from "@/features/pricing/lib/dodoReturnUrl";
import { track } from "@/lib/analytics";

import { CHECKOUT_RETURNED_PARAM } from "../constants";

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
 * A checkout started inside the wizard returns to
 * `/onboarding?checkout=returned` so the payment stage confirms in place. The
 * checkout store runs the one confirmation loop (fed by the return URL's
 * subscription id); this hook starts that wait and reads a failed outcome or
 * timeout off Dodo's query, which is consumed once and stripped from the URL.
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
    failed: params.get(DODO_RETURN_PARAM.status) === "failed",
    subscriptionId: params.get(DODO_RETURN_PARAM.subscriptionId) ?? undefined,
  };
}

export function useCheckoutReturn(): CheckoutReturn {
  const searchParams = useSearchParams();
  // Read Dodo's query once, into state, then strip it from the URL right
  // away: the outcome lives here for the rest of the visit, and nothing that
  // reloads, shares or bookmarks the page can replay a stale checkout.
  const [{ returned, failed, subscriptionId }, setReturnParams] = useState(() =>
    readReturnParams(new URLSearchParams(searchParams.toString())),
  );
  useEffect(() => {
    stripCheckoutReturnParams([CHECKOUT_RETURNED_PARAM]);
  }, []);
  const { checkoutPhase, confirmReturnedCheckout, clearError } =
    useDodoPayments();

  const waiting = returned && !failed;
  useEffect(() => {
    if (waiting) confirmReturnedCheckout(subscriptionId);
  }, [waiting, subscriptionId, confirmReturnedCheckout]);

  const isLate = waiting && checkoutPhase === "timeout";
  const timedOut = waiting && checkoutPhase === "unconfirmed";

  // A checkout that never became a subscription is invisible to the server:
  // a declined charge produces no webhook, and a webhook that never lands
  // produces nothing at all. Only the browser sees either outcome.
  const outcomeTrackedRef = useRef(false);
  useEffect(() => {
    if (!returned || outcomeTrackedRef.current) return;
    if (!failed && !timedOut) return;
    outcomeTrackedRef.current = true;
    track("subscription:failed", {
      source: "onboarding",
      reason: failed ? "declined" : "confirmation_timeout",
    });
  }, [returned, failed, timedOut]);

  const retry = () => {
    track("onboarding:checkout_retried", {
      reason: failed ? "declined" : "confirmation_timeout",
    });
    outcomeTrackedRef.current = false;
    clearError();
    setReturnParams(NOT_RETURNED);
  };

  return { returned, isLate, failed, timedOut, retry };
}
