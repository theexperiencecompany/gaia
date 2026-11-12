/**
 * An API amount is minor units in its own currency. Dividing every amount by
 * 100 shows ¥1000 as ¥10 and 1.500 KWD as 15.00; the exponent is the currency's.
 */
import { describe, expect, it } from "vitest";

import {
  currencyExponent,
  formatMoney,
  formatWholeOrCents,
  toMajorUnits,
} from "@/features/pricing/utils/money";
import { getPriceDisplay } from "@/features/pricing/utils/priceDisplay";
import { getSubscriptionSummary } from "@/features/settings/utils/subscriptionSummary";

describe("money", () => {
  it("divides by the currency's own exponent", () => {
    expect(currencyExponent("USD")).toBe(2);
    expect(currencyExponent("JPY")).toBe(0);
    expect(currencyExponent("KWD")).toBe(3);
    expect(currencyExponent("CLF")).toBe(4);
    expect(currencyExponent("UYW")).toBe(4);
    expect(toMajorUnits(1000, "JPY")).toBe(1000);
    expect(toMajorUnits(1500, "KWD")).toBe(1.5);
  });

  it("formats with the charged currency's symbol", () => {
    expect(formatMoney(2584, "EUR")).toBe("€25.84");
    expect(formatMoney(1000, "JPY")).toBe("¥1,000");
  });

  it("a whole-dollar price drops its cents, and zero reads Free", () => {
    expect(formatWholeOrCents(3000, "USD")).toBe("$30");
    expect(formatWholeOrCents(3050, "USD")).toBe("$30.50");
    expect(formatWholeOrCents(0, "USD")).toBe("Free");
  });

  it("a pricing card spreads a yearly price over twelve months to the minor unit, never a whole one", () => {
    const perMonth = (amountMinor: number, isMonthly: boolean, code: string) =>
      formatWholeOrCents(
        getPriceDisplay(amountMinor, undefined, isMonthly).perMonthMinor,
        code,
      );

    expect(perMonth(27000, false, "USD")).toBe("$22.50");
    expect(perMonth(30000, false, "USD")).toBe("$25");
    expect(perMonth(10000, false, "JPY")).toBe("¥833");
    expect(perMonth(1000, true, "JPY")).toBe("¥1,000");
  });

  it("the settings summary prices a resolved plan in the plan's own currency", () => {
    const summary = getSubscriptionSummary({
      user_id: "user_1",
      current_plan: {
        id: "plan_jpy",
        dodo_product_id: "pdt_jpy",
        name: "Pro",
        plan_type: "pro",
        description: null,
        amount: 1000,
        currency: "JPY",
        duration: "monthly",
        max_users: 1,
        features: [],
        is_active: true,
        created_at: "",
        updated_at: "",
      },
      subscription: null,
      is_subscribed: true,
      days_remaining: null,
      can_upgrade: true,
      can_downgrade: true,
      has_ever_subscribed: true,
      has_subscription: true,
      plan_type: "pro",
      status: "active",
    });

    expect(summary.priceFormatted).toBe("¥1,000");
  });
});
