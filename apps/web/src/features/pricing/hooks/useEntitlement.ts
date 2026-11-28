"use client";

import { UNPAID_APP_ROUTES } from "@/features/auth/constants";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { usePathname } from "@/i18n/navigation";

import { useIsPaid } from "./useIsPaid";
import { useUserSubscriptionStatus } from "./usePricing";

/**
 * What the signed-in account may use, from the web's one plan read.
 *
 * - entitled: on Pro, or billing is off on this deployment.
 * - lapsed: subscribed before, not now; the app's 402s raise the UpgradeModal.
 * - never_subscribed: finishes onboarding on its paywall; in the app, the same UpgradeModal.
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
 * Whether the app session (sidebar data, sync, realtime, notifications) may run.
 * A signed-in account gets it at once, so the plan read never holds the app
 * back; an unpaid account's 402s raise the UpgradeModal.
 * The exception is the routes an unpaid account lives on (the wizard's
 * paywall): there it mounts only for a plan known to allow it, so nothing
 * 402s behind the paywall.
 */
export function useAppSessionEnabled(): boolean {
  const entitlement = useEntitlement();
  const userId = useCurrentUser()?.user_id;
  const pathname = usePathname();
  const planAllows = entitlement === "entitled" || entitlement === "lapsed";
  if (UNPAID_APP_ROUTES.includes(pathname)) return planAllows;
  return planAllows || !!userId;
}
