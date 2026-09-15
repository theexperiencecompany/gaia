/**
 * A viewer's relationship to a single pricing plan card. Replaces three
 * booleans (`isCurrentPlan`, `hasActiveSubscription`, `isSubscriptionStatusUnknown`)
 * that were never orthogonal — they could represent impossible combinations
 * (e.g. "current plan" AND "status unknown") and pushed PricingCard over
 * react-doctor's boolean-prop limit. Derived once per card via
 * `getPlanViewerState`; PricingCard just switches on it.
 */
export type PlanViewerState =
  | "unknown" // subscription status not yet resolved (cold cache / rehydrating store) — never treat as "available"
  | "current" // this card is the plan the viewer is actively subscribed to
  | "subscribedElsewhere" // viewer has an active subscription, but to a different plan
  | "available"; // no active subscription on this plan (never subscribed, or a lapsed former subscription)

interface PlanViewerStateInput {
  isSubscriptionStatusUnknown: boolean;
  isCurrentPlan: boolean;
  hasActiveSubscription: boolean;
}

export function getPlanViewerState({
  isSubscriptionStatusUnknown,
  isCurrentPlan,
  hasActiveSubscription,
}: PlanViewerStateInput): PlanViewerState {
  if (isSubscriptionStatusUnknown) return "unknown";
  if (isCurrentPlan && hasActiveSubscription) return "current";
  if (hasActiveSubscription) return "subscribedElsewhere";
  return "available";
}
