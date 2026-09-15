"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "@/lib/toast";

import { type CheckoutSource, pricingApi } from "../api/pricingApi";
import { LAST_CHECKOUT_PRODUCT_KEY } from "../constants";
import {
  type CheckoutBillingCycle,
  useCheckoutOverlayStore,
} from "../stores/checkoutOverlayStore";
import { useUserSubscriptionStatus } from "./usePricing";

interface CheckoutOptions {
  /** Where this checkout was started from. Required at every call site: it
   *  rides to the server, which is what splits gate-driven revenue from
   *  pricing-page revenue on `payment:checkout_started`. */
  source: CheckoutSource;
  discountCode?: string;
}

export const useDodoPayments = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checkoutPhase = useCheckoutOverlayStore((s) => s.phase);
  const checkoutError = useCheckoutOverlayStore((s) => s.error);
  const startOverlayCheckout = useCheckoutOverlayStore((s) => s.startCheckout);
  const resetOverlayCheckout = useCheckoutOverlayStore((s) => s.reset);
  const confirmReturnedCheckout = useCheckoutOverlayStore(
    (s) => s.confirmReturnedCheckout,
  );
  const { refetch: refetchSubscription } = useUserSubscriptionStatus();

  // The store polls the raw endpoint; this is what pushes its answer into the
  // shared `["subscription-status"]` cache every paid-only gate reads. Both
  // endings matter: a checkout we gave up on hands the plans back, and a
  // charge that landed just after we stopped asking must not be met with a
  // Subscribe button by someone who has already paid.
  useEffect(() => {
    if (checkoutPhase === "confirmed" || checkoutPhase === "unconfirmed")
      void refetchSubscription();
  }, [checkoutPhase, refetchSubscription]);

  const createSubscriptionAndRedirect = useCallback(
    async (productId: string, { source, discountCode }: CheckoutOptions) => {
      setIsLoading(true);
      setError(null);

      try {
        // `source` goes to the server rather than into a capture here: the API
        // owns payment:checkout_started on both the redirect and overlay paths,
        // so the funnel reads one event name split by source/surface.
        const result = await pricingApi.createSubscription({
          product_id: productId,
          source,
          ...(discountCode ? { discount_code: discountCode } : {}),
        });

        // Redirect user to Dodo payment link
        if (result.payment_link) {
          // Remember the plan so the result page can restart checkout on retry.
          localStorage.setItem(LAST_CHECKOUT_PRODUCT_KEY, productId);
          window.location.href = result.payment_link;
        } else {
          throw new Error("Payment link not received");
        }
      } catch (err) {
        // No capture here: this failure came back from the API, which already
        // saw it and owns the event for it. A second one from the browser
        // would double-count the same refusal.
        const errorMessage =
          err instanceof Error ? err.message : "Failed to create subscription";
        setError(errorMessage);
        toast.error(errorMessage);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  /** The preferred path: pay inside the app, no redirect. Falls back to
   *  nothing — a failure surfaces through `checkoutError` and the caller stays
   *  where it is. */
  const openCheckoutOverlay = useCallback(
    async (billingCycle: CheckoutBillingCycle, { source }: CheckoutOptions) => {
      try {
        await startOverlayCheckout(billingCycle, source);
      } catch (err) {
        // Same as above: the session the server refused to mint is the
        // server's event to emit, not ours.
        toast.error(
          err instanceof Error ? err.message : "Failed to start checkout",
        );
      }
    },
    [startOverlayCheckout],
  );

  const clearError = useCallback(() => {
    setError(null);
    resetOverlayCheckout();
  }, [resetOverlayCheckout]);

  return {
    createSubscriptionAndRedirect,
    openCheckoutOverlay,
    confirmReturnedCheckout,
    checkoutPhase,
    isLoading,
    error: error ?? checkoutError,
    clearError,
  };
};
