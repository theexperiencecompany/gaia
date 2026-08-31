"use client";

import { useUser } from "@/features/auth/hooks/useUser";

import { useUserSubscriptionStatus } from "./usePricing";

export interface IsPaidResult {
  isPaid: boolean;
  /** True while the subscription-status query is still in flight (e.g. a
   * cold cache right after a hard refresh — it's excluded from the
   * IndexedDB persister allowlist, so it always starts unresolved). Callers
   * that gate an action on `isPaid` must not treat "loading" as "not paid":
   * that traps a paying user behind the paywall until the query resolves. */
  isLoading: boolean;
}

/**
 * Whether the signed-in user has an active Pro subscription. Reuses the same
 * `["subscription-status"]` react-query cache that `usePricing` /
 * `SubscriptionSettings` already populate — never issues a second fetch. A
 * logged-out user is never treated as paid.
 */
export function useIsPaid(): IsPaidResult {
  const user = useUser();
  const { data: subscriptionStatus, isLoading } = useUserSubscriptionStatus();
  return {
    isPaid: !!user.userId && subscriptionStatus?.plan_type === "pro",
    isLoading,
  };
}
