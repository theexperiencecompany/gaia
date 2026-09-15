import type {
  Plan,
  UserSubscriptionStatus,
} from "@/features/pricing/api/pricingApi";

export type ReceiptDetails = {
  planName?: string;
  amount: number | null;
  currency?: string;
  billingPeriod?: string;
  nextBillingDate: string | null;
  subscriptionRef: string | null;
  purchasedAt: string | null;
  quantity?: number;
};

/**
 * Receipt rows for the post-payment page. The webhook-verified subscription
 * record is the source of truth — every printed row comes from that one
 * endpoint, so the reference can never describe a different subscription
 * than the plan/amount next to it. Before verification lands, the plan from
 * the remembered checkout click stands in as a preview.
 */
export function buildReceiptDetails(
  subscriptionStatus: UserSubscriptionStatus | null | undefined,
  previewPlan: Plan | undefined,
): ReceiptDetails {
  const isSubscribed = subscriptionStatus?.is_subscribed === true;
  if (!isSubscribed) {
    return {
      planName: previewPlan?.name,
      amount: previewPlan?.amount ?? null,
      currency: previewPlan?.currency ?? undefined,
      billingPeriod: previewPlan?.duration,
      nextBillingDate: null,
      subscriptionRef: null,
      purchasedAt: null,
      quantity: undefined,
    };
  }

  const activePlan = subscriptionStatus?.current_plan;
  const subscription = subscriptionStatus?.subscription;
  return {
    planName: activePlan?.name ?? previewPlan?.name,
    amount:
      subscription?.recurring_pre_tax_amount ?? activePlan?.amount ?? null,
    currency: subscription?.currency ?? activePlan?.currency ?? undefined,
    billingPeriod: activePlan?.duration ?? previewPlan?.duration,
    nextBillingDate: subscription?.next_billing_date ?? null,
    subscriptionRef: subscription?.dodo_subscription_id ?? null,
    purchasedAt:
      subscription?.previous_billing_date ?? subscription?.created_at ?? null,
    quantity: subscription?.quantity,
  };
}
