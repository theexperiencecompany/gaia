import type { Plan } from "../api/pricingApi";

/** Whether a `Plan` row is the contact-sales tier — quoted, never checked out. */
export function isEnterprisePlan(plan: Plan): boolean {
  return plan.plan_type === "enterprise";
}

/** Whether a `Plan` row is GAIA's paid (Pro) tier. */
export function isProPlan(plan: Plan): boolean {
  return plan.plan_type === "pro";
}

/** GAIA sells one plan, so the card says "GAIA" rather than the tier's
 * internal name. Display only: the backend, webhooks and entitlements keep
 * "Pro", so existing subscriptions are untouched. */
const PLAN_DISPLAY_NAME = "GAIA";

export function displayPlanName(plan: Plan): string {
  return isProPlan(plan) ? PLAN_DISPLAY_NAME : plan.name;
}
