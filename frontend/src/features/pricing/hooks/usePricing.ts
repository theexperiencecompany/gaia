"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { useUser } from "@/features/auth/hooks/useUser";

import { Plan, pricingApi } from "../api/pricingApi";

export const usePricing = (initialPlans: Plan[] = []) => {
  const [error, setError] = useState<string | null>(null);
  const user = useUser();

  // Get all plans (no authentication required)
  const {
    data: plans = [],
    isLoading: plansLoading,
    error: plansError,
    isError: isPlansError,
  } = useQuery({
    queryKey: ["plans"],
    queryFn: () => pricingApi.getPlans(),
    staleTime: 5 * 60 * 1000, // 5 minutes
    initialData: initialPlans.length > 0 ? initialPlans : undefined,
    retry: 2, // Retry failed requests
  });

  // Get user subscription status (only when authenticated)
  const {
    data: subscriptionStatus,
    isLoading: subscriptionLoading,
    error: subscriptionError,
    refetch: refetchSubscription,
  } = useQuery({
    queryKey: ["subscription-status"],
    queryFn: () => pricingApi.getSubscriptionStatus(),
    staleTime: 1 * 60 * 1000, // 1 minute
    enabled: !!user, // Only fetch when user is logged in
    retry: false, // Don't retry on auth failures
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

    // Loading states - plans can load independently of subscription
    isLoading: plansLoading || (user && subscriptionLoading),
    plansLoading,
    subscriptionLoading: user ? subscriptionLoading : false,

    // Errors - only show error if plans failed AND we have no data
    error: error || (isPlansError && plans.length === 0 ? plansError : null),
    plansError,
    subscriptionError: user ? subscriptionError : null,

    // Methods
    verifyPayment,
    getPlanById,
    clearError,
    refetchSubscription,
  };
};

// Separate hook for just subscription status (for backward compatibility)
export const useUserSubscriptionStatus = () => {
  const user = useUser();

  return useQuery({
    queryKey: ["subscription-status"],
    queryFn: () => pricingApi.getSubscriptionStatus(),
    staleTime: 1 * 60 * 1000, // 1 minute
    enabled: !!user, // Only fetch when user is logged in
    retry: false, // Don't retry on auth failures
  });
};
