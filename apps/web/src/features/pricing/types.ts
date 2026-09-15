/**
 * A viewer's relationship to a single pricing plan card.
 *
 * PricingCard used to take three independent booleans — `isCurrentPlan`,
 * `hasActiveSubscription`, `isSubscriptionStatusUnknown` — but they were
 * never orthogonal: only one of "status not yet known", "this is my active
 * plan", "I'm actively subscribed to a different plan", or "I'm not actively
 * subscribed to this plan" can be true for a given card at a time. Threading
 * them separately let PricingCard represent combinations that can't happen
 * (e.g. "current plan" AND "status unknown") and pushed the component over
 * react-doctor's boolean-prop limit. `PlanViewerState` makes the impossible
 * combinations unrepresentable; PricingCards derives it once per card via
 * `getPlanViewerState`, PricingCard just switches on it.
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
