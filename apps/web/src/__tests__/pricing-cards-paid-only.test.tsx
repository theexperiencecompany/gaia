// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { Plan } from "@/features/pricing/api/pricingApi";

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    SUBSCRIPTION_PLAN_VIEWED: "subscription:plan_viewed",
    PRICING_PLAN_SELECTED: "pricing:plan_selected",
  },
  trackEvent: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useUser", () => ({
  useUser: () => ({ userId: undefined }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/features/pricing/hooks/useDodoPayments", () => ({
  useDodoPayments: () => ({
    createSubscriptionAndRedirect: vi.fn(),
    isLoading: false,
    error: null,
  }),
}));

const FREE_PLAN: Plan = {
  id: "plan_free",
  dodo_product_id: "dodo_free",
  name: "Free",
  amount: 0,
  currency: "USD",
  duration: "monthly",
  features: ["Basic chat"],
  is_active: true,
  created_at: "",
  updated_at: "",
};

const PRO_PLAN: Plan = {
  id: "plan_pro",
  dodo_product_id: "dodo_pro_monthly",
  name: "Pro",
  amount: 2000,
  currency: "USD",
  duration: "monthly",
  features: ["Unlimited chat", "Workflows"],
  is_active: true,
  created_at: "",
  updated_at: "",
};

let mockPlans: Plan[] = [];

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({
    plans: mockPlans,
    isLoading: false,
    error: null,
    subscriptionStatus: undefined,
  }),
}));

// Imported after the mocks above so PricingCards picks up the mocked hooks.
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { isProPlan } from "@/features/pricing/utils/planPredicates";

describe("PricingCards paid-only rendering", () => {
  // TextMorph (torph) reads window.matchMedia for reduced-motion detection;
  // jsdom doesn't implement it.
  beforeAll(() => {
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
    // TextMorph also calls Element.getAnimations for its exit transition;
    // jsdom doesn't implement the Web Animations API.
    if (!Element.prototype.getAnimations) {
      Element.prototype.getAnimations = () => [];
    }
  });

  it("renders only the paid plan when the backend returns no $0 row", () => {
    mockPlans = [PRO_PLAN];
    render(<PricingCards durationIsMonth hideEnterprise />);

    expect(screen.getByText("Pro")).not.toBeNull();
    expect(screen.queryByText("Free")).toBeNull();
  });

  it("filters out a $0 plan row even when the backend still returns one", () => {
    mockPlans = [FREE_PLAN, PRO_PLAN];
    render(<PricingCards durationIsMonth hideEnterprise />);

    expect(screen.getByText("Pro")).not.toBeNull();
    expect(screen.queryByText("Free")).toBeNull();
  });
});

describe("isProPlan", () => {
  it("matches a plan named exactly Pro, case-insensitively", () => {
    expect(isProPlan({ ...PRO_PLAN, name: "Pro" })).toBe(true);
    expect(isProPlan({ ...PRO_PLAN, name: "pro" })).toBe(true);
    expect(isProPlan({ ...PRO_PLAN, name: " PRO " })).toBe(true);
  });

  it("does not match an unrelated plan whose name merely contains 'pro'", () => {
    // The old `.name.toLowerCase().includes("pro")` check would have
    // wrongly matched both of these as the Pro tier.
    expect(isProPlan({ ...PRO_PLAN, name: "Proactive", amount: 0 })).toBe(
      false,
    );
    expect(isProPlan({ ...FREE_PLAN, name: "Property Manager" })).toBe(false);
  });

  it("falls back to any priced, non-Enterprise plan when the name isn't 'Pro'", () => {
    expect(isProPlan({ ...PRO_PLAN, name: "Growth", amount: 4900 })).toBe(true);
  });

  it("never matches a $0 plan or an Enterprise-named plan via the fallback", () => {
    expect(isProPlan(FREE_PLAN)).toBe(false);
    expect(isProPlan({ ...PRO_PLAN, name: "Enterprise", amount: 9900 })).toBe(
      false,
    );
  });
});
