"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { Plan, pricingApi } from "../api/pricingApi";

export const usePricing = (initialPlans: Plan[] = []) => {
  const [error, setError] = useState<string | null>(null);

  // Get all plans
  const {
    data: plans = [],
    isLoading: plansLoading,
    error: plansError,
  } = useQuery({
    queryKey: ["plans"],
    queryFn: () => pricingApi.getPlans(),
    staleTime: 5 * 60 * 1000, // 5 minutes
    initialData: initialPlans.length > 0 ? initialPlans : undefined,
  });

  // Get user subscription status
  const {
    data: subscriptionStatus,
    isLoading: subscriptionLoading,
    error: subscriptionError,
    refetch: refetchSubscription,
  } = useQuery({
    queryKey: ["subscription-status"],
    queryFn: () => pricingApi.getSubscriptionStatus(),
    staleTime: 1 * 60 * 1000, // 1 minute
  });

  // Verify payment status
  const verifyPayment = useCallback(async () => {
    try {
      setError(null);
      const result = await pricingApi.verifyPayment();

      // Refetch subscription status after verification
      await refetchSubscription();

      return result;
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Payment verification failed";
      setError(errorMessage);
      throw err;
    }
  }, [refetchSubscription]);

  // Get plan by ID
  const getPlanById = useCallback(
    (planId: string): Plan | undefined => {
      return plans.find((plan) => plan.id === planId);
    },
    [plans],
  );

  // Clear error
  const clearError = useCallback(() => {
    setError(null);
  }, []);

  return {
    // Data
    plans,
    subscriptionStatus,

    // Loading states
    isLoading: plansLoading || subscriptionLoading,
    plansLoading,
    subscriptionLoading,

    // Errors
    error: error || plansError || subscriptionError,
    plansError,
    subscriptionError,

    // Methods
    verifyPayment,
    getPlanById,
    clearError,
    refetchSubscription,
  };
};

// Separate hook for just subscription status (for backward compatibility)
export const useUserSubscriptionStatus = () => {
  return useQuery({
    queryKey: ["subscription-status"],
    queryFn: () => pricingApi.getSubscriptionStatus(),
    staleTime: 1 * 60 * 1000, // 1 minute
  });
};
