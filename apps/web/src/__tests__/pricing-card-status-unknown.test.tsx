// @vitest-environment jsdom
//
// Regression coverage found while closing out the "unknown treated as free"
// bug class: PricingCard's `isCurrentPlan` / `hasActiveSubscription` derive
// from the raw subscription-status query in PricingCards, which reads
// `undefined` while the plan status is genuinely not yet known (cold cache /
// user store rehydrating). Before this fix that made `isOnFreePlan`-style
// logic read "not subscribed" for a paying user, and — worse — let them
// click straight into `createSubscriptionAndRedirect`, risking a duplicate
// checkout. The fix threads `isSubscriptionStatusUnknown` down from
// PricingCards and holds the CTA disabled (never actionable) while true.
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    SUBSCRIPTION_PLAN_VIEWED: "subscription:plan_viewed",
    PRICING_PLAN_SELECTED: "pricing:plan_selected",
  },
  trackEvent: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useUser", () => ({
  useUser: () => ({ userId: "user_1" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const createSubscriptionAndRedirect = vi.fn();
vi.mock("@/features/pricing/hooks/useDodoPayments", () => ({
  useDodoPayments: () => ({
    createSubscriptionAndRedirect,
    isLoading: false,
    error: null,
  }),
}));

import { PricingCard } from "@/features/pricing/components/PricingCard";

describe("PricingCard — CTA vs. plan status unknown", () => {
  beforeAll(() => {
    // TextMorph (torph) reads window.matchMedia for reduced-motion detection.
    window.matchMedia =
      window.matchMedia ||
      ((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }));
    if (!Element.prototype.getAnimations) {
      Element.prototype.getAnimations = () => [];
    }
  });

  beforeEach(() => {
    createSubscriptionAndRedirect.mockReset();
  });

  it("lets a logged-in user click into checkout once plan status is known", () => {
    render(
      <PricingCard
        title="Pro"
        price={2000}
        durationIsMonth
        planId="dodo_pro_monthly"
        isCurrentPlan={false}
        hasActiveSubscription={false}
        isSubscriptionStatusUnknown={false}
      />,
    );

    const button = screen.getByRole("button", {
      name: /Get GAIA Pro/i,
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(createSubscriptionAndRedirect).toHaveBeenCalledTimes(1);
  });

  it("holds the CTA disabled and does not start a checkout while the plan status is still unknown", () => {
    render(
      <PricingCard
        title="Pro"
        price={2000}
        durationIsMonth
        planId="dodo_pro_monthly"
        isCurrentPlan={false}
        hasActiveSubscription={false}
        isSubscriptionStatusUnknown
      />,
    );

    // Before the fix, isCurrentPlan/hasActiveSubscription being false in this
    // exact window meant the button rendered as an actionable "Get GAIA Pro"
    // — a paying user reloading mid-fetch could click straight into a
    // duplicate subscription checkout.
    const button = screen.getByRole("button", {
      name: /Checking your plan/i,
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(createSubscriptionAndRedirect).not.toHaveBeenCalled();
  });
});
