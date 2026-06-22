"use client";

import { useCallback, useState } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

import { pricingApi } from "../api/pricingApi";
import { LAST_CHECKOUT_PRODUCT_KEY } from "../constants";

export const useDodoPayments = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createSubscriptionAndRedirect = useCallback(
    async (productId: string) => {
      setIsLoading(true);
      setError(null);

      try {
        // Track checkout started
        trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_CHECKOUT_STARTED, {
          planId: productId,
        });

        // Create subscription via API - backend handles user authentication via JWT
        const result = await pricingApi.createSubscription({
          product_id: productId,
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
