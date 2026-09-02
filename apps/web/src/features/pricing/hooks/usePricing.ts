"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { useUser } from "@/features/auth/hooks/useUser";

import { type Plan, pricingApi } from "../api/pricingApi";

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
    enabled: !!user.userId, // Only fetch once the persisted user store has a real id
    retry: false, // Don't retry on auth failures
  });

  // Verify payment status
  const verifyPayment = useCallback(
    async (subscriptionId?: string | null) => {
      try {
        setError(null);
        const result = await pricingApi.verifyPayment(subscriptionId);

        // Refetch subscription status after verification
        await refetchSubscription();

        return result;
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Payment verification failed";
        setError(errorMessage);
        throw err;
      }
    },
    [refetchSubscription],
  );

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
    enabled: !!user.userId, // Only fetch once the persisted user store has a real id
    retry: false, // Don't retry on auth failures
  });
};

/**
 * Whether the subscription plan is not yet definitively known: the persisted
 * user store hasn't rehydrated with a real id yet, or the (consequently
 * disabled, or still-pending) `["subscription-status"]` query hasn't
 * produced data yet. Deliberately keyed off `data === undefined`, never off
 * `isLoading` — in TanStack Query v5 a disabled query reports
 * `isLoading === false` even though it has never fetched, which would
 * otherwise read as "answered" when it is really "unasked". See
 * `useIsPaid` for the invariant this backs: never treat "unknown" as
 * "free"/"not paid".
 */
export function useIsSubscriptionStatusUnknown(): boolean {
  const user = useUser();
  const { data } = useUserSubscriptionStatus();
  return !user.userId || data === undefined;
}
