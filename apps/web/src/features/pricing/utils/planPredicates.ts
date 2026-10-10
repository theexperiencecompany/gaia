import type { Plan } from "../api/pricingApi";

const PRO_PLAN_NAME = "pro";
const ENTERPRISE_PLAN_NAME = "enterprise";

/** Whether a `Plan` row is the contact-sales tier — quoted, never checked out. */
export function isEnterprisePlan(plan: Plan): boolean {
  return plan.name.toLowerCase().includes(ENTERPRISE_PLAN_NAME);
}

/**
 * Whether a Plan row is GAIA's paid (Pro) tier.
 *
 * PlanResponse carries no plan_type, so this is the single place that infers it.
 * The name match is exact, not includes("pro") — that matches "Proactive" too —
 * and falls back to any priced non-Enterprise plan.
 */
/** GAIA sells one plan, so the card says "GAIA" rather than the tier's
 * internal name. Display only: the backend, webhooks and entitlements keep
 * "Pro", so existing subscriptions are untouched. */
const PLAN_DISPLAY_NAME = "GAIA";

export function displayPlanName(plan: Plan): string {
  return isProPlan(plan) ? PLAN_DISPLAY_NAME : plan.name;
}

export function isProPlan(plan: Plan): boolean {
  const name = plan.name.trim().toLowerCase();
  if (name === PRO_PLAN_NAME) return true;
  return plan.amount > 0 && !isEnterprisePlan(plan);
}
