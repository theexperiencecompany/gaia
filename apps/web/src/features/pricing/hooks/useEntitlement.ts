"use client";

import { useDeployment } from "@/features/settings/hooks/useSetupStatus";

import { useIsPaid } from "./useIsPaid";
import { useUserSubscriptionStatus } from "./usePricing";

/**
 * What the signed-in account may use, from the web's one plan read.
 *
 * - entitled: on Pro, or billing is off on this deployment.
 * - lapsed: subscribed before, not now; the app's 402s raise the UpgradeModal.
 * - never_subscribed: belongs on the onboarding paywall, never in the app.
 * - unknown: the plan has not been read yet.
 */
export type Entitlement =
  | "entitled"
  | "lapsed"
  | "never_subscribed"
  | "unknown";

export function useEntitlement(): Entitlement {
  const billingEnabled = useDeployment().bills;
  const { isPaid, isUnknown, hasEverSubscribed } = useIsPaid();
  const { isError } = useUserSubscriptionStatus();

  if (!billingEnabled) return "entitled";
  // An unreadable plan is not a refusal: the backend's 402 stays the enforcement.
  if (isError) return "entitled";
  if (isUnknown) return "unknown";
  if (isPaid) return "entitled";
  return hasEverSubscribed ? "lapsed" : "never_subscribed";
}

/**
 * Whether the paid app session (sidebar data, sync, realtime, notifications)
 * may run. Never for an account that has not paid or a plan not yet read:
 * every one of those requests would 402.
 */
export function useAppSessionEnabled(): boolean {
  const entitlement = useEntitlement();
  return entitlement === "entitled" || entitlement === "lapsed";
}
