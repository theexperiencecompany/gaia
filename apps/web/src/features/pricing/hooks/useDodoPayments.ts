"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";

import { trackSubscription } from "@/lib/analytics";

import { pricingApi } from "../api/pricingApi";

export const useDodoPayments = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createSubscriptionAndRedirect = useCallback(
    async (productId: string) => {
      setIsLoading(true);
      setError(null);

      try {
        // Track checkout started
        trackSubscription("started", {
          planId: productId,
        });

        // Create subscription via API - backend handles user authentication via JWT
        const result = await pricingApi.createSubscription({
          product_id: productId,
        });

        // Redirect user to Dodo payment link
        if (result.payment_link) {
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
        trackSubscription("failed", {
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
