import type { Plan } from "../api/pricingApi";

const PRO_PLAN_NAME = "pro";
const ENTERPRISE_PLAN_NAME = "enterprise";

/** Whether a `Plan` row is the contact-sales tier — quoted, never checked out. */
export function isEnterprisePlan(plan: Plan): boolean {
  return plan.name.toLowerCase().includes(ENTERPRISE_PLAN_NAME);
}

/**
 * Whether a `Plan` row is GAIA's paid (Pro) tier. `PlanResponse` on the
 * backend (`apps/api/app/models/payment_models.py`) has no typed
 * `plan_type` field the way a resolved `UserSubscriptionStatus` does — only
 * `name`/`amount`/`duration` — so this is the single place that infers it,
 * shared by `PaywallModal` and `PricingCards` so the two can never
 * independently disagree on which card is "Pro".
 *
 * Primary check is an exact (trimmed, case-insensitive) name match rather
 * than a substring — `.includes("pro")` also matches an unrelated plan
 * named e.g. "Proactive" or "Property". Falls back to "any priced,
 * non-Enterprise plan" for a renamed Pro row, since GAIA has no other paid
 * tier today.
 */
export function isProPlan(plan: Plan): boolean {
  const name = plan.name.trim().toLowerCase();
  if (name === PRO_PLAN_NAME) return true;
  return plan.amount > 0 && !isEnterprisePlan(plan);
}
