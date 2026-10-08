// @vitest-environment jsdom
/**
 * A plan row prices itself in its own currency: the card shows the row's
 * symbol, and a yearly saving is only claimed against a monthly row in the
 * same currency, since two currencies cannot be compared without a rate.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { Plan } from "@/features/pricing/api/pricingApi";

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { SUBSCRIPTION_PLAN_VIEWED: "subscription:plan_viewed" },
  trackEvent: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ userId: undefined }),
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

let mockPlans: Plan[] = [];

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({
    plans: mockPlans,
    isLoading: false,
    error: null,
    subscriptionStatus: undefined,
  }),
  useIsSubscriptionStatusUnknown: () => false,
}));

import { BillingPeriodTabs } from "@/features/pricing/components/BillingPeriodTabs";
import { PricingCards } from "@/features/pricing/components/PricingCards";

const PRO_MONTHLY: Plan = {
  id: "plan_m",
  dodo_product_id: "pdt_m",
  name: "Pro",
  plan_type: "pro",
  description: null,
  amount: 3000,
  currency: "EUR",
  duration: "monthly",
  max_users: 1,
  features: [],
  is_active: true,
  created_at: "",
  updated_at: "",
};

const PRO_YEARLY: Plan = {
  ...PRO_MONTHLY,
  id: "plan_y",
  dodo_product_id: "pdt_y",
  amount: 30000,
  duration: "yearly",
};

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
  if (!Element.prototype.getAnimations) {
    Element.prototype.getAnimations = () => [];
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("a non-USD catalogue", () => {
  it("prices the yearly card in the row's own currency", () => {
    mockPlans = [PRO_MONTHLY, PRO_YEARLY];
    const { container } = render(<PricingCards hideEnterprise />);

    const text = container.textContent ?? "";
    expect(text).toContain("€300");
    expect(text).not.toContain("$");
  });
});

describe("a monthly and a yearly row in different currencies", () => {
  it("the yearly card claims no months free", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mockPlans = [{ ...PRO_MONTHLY, currency: "USD" }, PRO_YEARLY];
    const { container } = render(<PricingCards hideEnterprise />);

    expect(container.textContent).not.toMatch(/months? free/);
  });

  it("claims no yearly saving, and says why", () => {
    const error = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    mockPlans = [{ ...PRO_MONTHLY, currency: "USD" }, PRO_YEARLY];
    render(<BillingPeriodTabs isYearly={false} onChange={vi.fn()} />);

    expect(screen.queryByText(/months? free|Save/)).toBeNull();
    expect(error).toHaveBeenCalled();
  });
});
