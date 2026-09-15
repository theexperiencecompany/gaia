"use client";

import {
  useIsSubscriptionStatusUnknown,
  useUserSubscriptionStatus,
} from "./usePricing";

export interface IsPaidResult {
  isPaid: boolean;
  /**
   * True while plan status isn't yet known (cold cache, rehydrating user
   * store, or a disabled/pending query) — derived from `data === undefined`,
   * never `isLoading` (a v5 disabled query reports false despite never fetching).
   * INVARIANT: never treat this as "not paid"; gate on `!isUnknown` and
   * assume-paid while unknown — the backend's 402 is the real enforcement.
   */
  isUnknown: boolean;
  /**
   * Whether this account has ever held a subscription — what separates a
   * lapsed customer from a never-paid one for copy (`paywallCopyFor`).
   * Undefined while unknown.
   */
  hasEverSubscribed: boolean | undefined;
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
    hasEverSubscribed: subscriptionStatus?.has_ever_subscribed,
  };
}
