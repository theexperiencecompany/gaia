import { describe, expect, it } from "vitest";
import type {
  Plan,
  Subscription,
  UserSubscriptionStatus,
} from "@/features/pricing/api/pricingApi";
import { buildReceiptDetails } from "@/features/pricing/utils/receiptDetails";

const proMonthly: Plan = {
  id: "plan_pro",
  dodo_product_id: "pdt_pro_monthly",
  name: "Pro",
  amount: 3000,
  currency: "USD",
  duration: "monthly",
  features: [],
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const subscription: Subscription = {
  id: "sub_row",
  dodo_subscription_id: "sub_0NmJsZG5B0qv7BmHWd8mk",
  user_id: "user_1",
  product_id: "pdt_pro_monthly",
  status: "active",
  quantity: 2,
  created_at: "2026-08-27T18:53:19.220Z",
  updated_at: "2026-08-27T18:53:19.220Z",
  currency: "INR",
  recurring_pre_tax_amount: 297948,
  next_billing_date: "2026-09-27T18:51:00.016538+00:00",
  previous_billing_date: "2026-08-27T18:50:43.294189+00:00",
};

function status(
  overrides: Partial<UserSubscriptionStatus>,
): UserSubscriptionStatus {
  return {
    user_id: "user_1",
    is_subscribed: false,
    can_upgrade: true,
    can_downgrade: false,
    ...overrides,
  };
}

describe("buildReceiptDetails", () => {
  it("previews the remembered plan while verification is pending", () => {
    const details = buildReceiptDetails(status({}), proMonthly);

    expect(details).toEqual({
      planName: "Pro",
      amount: 3000,
      currency: "USD",
      billingPeriod: "monthly",
      nextBillingDate: null,
      subscriptionRef: null,
      purchasedAt: null,
      quantity: undefined,
    });
  });

  it("prints nothing verifiable when neither status nor preview is known", () => {
    expect(buildReceiptDetails(undefined, undefined)).toEqual({
      planName: undefined,
      amount: null,
      currency: undefined,
      billingPeriod: undefined,
      nextBillingDate: null,
      subscriptionRef: null,
      purchasedAt: null,
      quantity: undefined,
    });
  });

  it("prints the verified subscription record, not the preview, once subscribed", () => {
    const details = buildReceiptDetails(
      status({
        is_subscribed: true,
        current_plan: proMonthly,
        subscription,
      }),
      { ...proMonthly, name: "Stale preview", amount: 1 },
    );

    // Charged amount/currency win over the catalog price: the receipt must
    // show what Dodo actually billed.
    expect(details).toEqual({
      planName: "Pro",
      amount: 297948,
      currency: "INR",
      billingPeriod: "monthly",
      nextBillingDate: "2026-09-27T18:51:00.016538+00:00",
      subscriptionRef: "sub_0NmJsZG5B0qv7BmHWd8mk",
      purchasedAt: "2026-08-27T18:50:43.294189+00:00",
      quantity: 2,
    });
  });

  it("falls back to the catalog price and creation date when the record is sparse", () => {
    const sparse: Subscription = {
      ...subscription,
      currency: undefined,
      recurring_pre_tax_amount: undefined,
      next_billing_date: undefined,
      previous_billing_date: undefined,
    };
    const details = buildReceiptDetails(
      status({
        is_subscribed: true,
        current_plan: proMonthly,
        subscription: sparse,
      }),
      undefined,
    );

    expect(details.amount).toBe(3000);
    expect(details.currency).toBe("USD");
    expect(details.nextBillingDate).toBeNull();
    expect(details.purchasedAt).toBe("2026-08-27T18:53:19.220Z");
  });

  it("keeps the preview plan name when the catalog has no match for the record", () => {
    const details = buildReceiptDetails(
      status({ is_subscribed: true, current_plan: undefined, subscription }),
      proMonthly,
    );

    expect(details.planName).toBe("Pro");
    expect(details.billingPeriod).toBe("monthly");
    expect(details.subscriptionRef).toBe("sub_0NmJsZG5B0qv7BmHWd8mk");
  });
});
