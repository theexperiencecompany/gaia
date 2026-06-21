"use client";

import { useEffect } from "react";

import { setUserProperties } from "@/lib/analytics";

import { useUserSubscriptionStatus } from "./usePricing";

/**
 * Keeps PostHog person properties in sync with the user's authoritative
 * subscription status so dashboards can segment pro vs free users.
 *
 * The backend is the source of truth for *becoming* a paying customer (it fires
 * `subscription:activated` only after a verified Dodo webhook). This hook mirrors
 * the resulting state onto the person each session, which also self-heals on
 * downgrade/churn — something a one-shot activation event cannot do.
 */
export const useSubscriptionAnalyticsSync = (): void => {
  const { data: status } = useUserSubscriptionStatus();

  useEffect(() => {
    if (!status) return;

    setUserProperties({
      is_subscribed: status.is_subscribed,
      plan: status.plan_type ?? (status.is_subscribed ? "pro" : "free"),
    });
  }, [status]);
};
