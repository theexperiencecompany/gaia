"use client";

import {
  useIsSubscriptionStatusUnknown,
  useUserSubscriptionStatus,
} from "./usePricing";

export interface IsPaidResult {
  isPaid: boolean;
  /**
   * True whenever the plan status is not yet definitively known — a cold
   * cache right after a hard refresh, the persisted user store still
   * rehydrating, or the subscription-status query still disabled/pending
   * because of that. Derived from `data === undefined` (plus user
   * hydration), never from TanStack Query's `isLoading`: in v5 a *disabled*
   * query reports `isLoading === false` even though it has never fetched,
   * so `isLoading` alone cannot distinguish "answered: free" from "hasn't
   * answered yet".
   *
   * INVARIANT: a consumer must never treat `isUnknown === true` as "not
   * paid" — gate the free-tier UI / paywall / block on `!isUnknown`, and
   * either render nothing, a neutral/skeleton state, or assume-paid while
   * unknown. The backend's 402 on protected endpoints is the real
   * enforcement, so erring toward "assume paid until told otherwise" here
   * is safe.
   */
  isUnknown: boolean;
}

/**
 * Whether the signed-in user has an active Pro subscription. Reuses the same
 * `["subscription-status"]` react-query cache that `usePricing` /
 * `SubscriptionSettings` already populate — never issues a second fetch. A
 * logged-out user is never treated as paid.
 */
export function useIsPaid(): IsPaidResult {
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const isUnknown = useIsSubscriptionStatusUnknown();

  return {
    isPaid: !isUnknown && subscriptionStatus?.plan_type === "pro",
    isUnknown,
  };
}
