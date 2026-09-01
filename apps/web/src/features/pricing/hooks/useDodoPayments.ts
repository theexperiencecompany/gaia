"use client";

import { useCallback, useState } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

import { pricingApi } from "../api/pricingApi";
import { LAST_CHECKOUT_PRODUCT_KEY } from "../constants";

/** Where a checkout was started from — the paid-only gate, or a place the
 *  user chose to upgrade on their own. Required at every call site so the
 *  funnel can separate gate-driven revenue from pricing-page revenue. */
export type CheckoutSource =
  | "paywall_modal"
  | "pricing_card"
  | "payment_retry"
  | "checkout_resume";

interface CheckoutOptions {
  source: CheckoutSource;
  discountCode?: string;
}

export const useDodoPayments = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createSubscriptionAndRedirect = useCallback(
    async (productId: string, { source, discountCode }: CheckoutOptions) => {
      setIsLoading(true);
      setError(null);

      try {
        // Every checkout funnels through here, so this is the single emitter
        // for the event — a second capture at a call site would double-count
        // that path against the ones that only fire here.
        trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_CHECKOUT_STARTED, {
          planId: productId,
          source,
        });

        // Create subscription via API - backend handles user authentication via JWT
        const result = await pricingApi.createSubscription({
          product_id: productId,
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
        const errorMessage =
          err instanceof Error ? err.message : "Failed to create subscription";
        setError(errorMessage);
        toast.error(errorMessage);

        // Track checkout failure
        trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_FAILED, {
          planId: productId,
          source,
          reason: errorMessage,
        });
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  return {
    createSubscriptionAndRedirect,
    isLoading,
    error,
    clearError,
  };
};
