// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createSubscriptionAndRedirect = vi.fn();
const logout = vi.fn();

let isPaid = false;
let isSubscriptionStatusLoading = false;

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    SUBSCRIPTION_CHECKOUT_STARTED: "subscription:checkout_started",
  },
  trackEvent: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useLogout", () => ({
  useLogout: () => ({ logout }),
}));

vi.mock("@/features/pricing/hooks/useDodoPayments", () => ({
  useDodoPayments: () => ({
    createSubscriptionAndRedirect,
    isLoading: false,
    error: null,
    clearError: vi.fn(),
  }),
}));

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({
    isPaid,
    isLoading: isSubscriptionStatusLoading,
  }),
}));

const PRO_PLAN = {
  id: "plan_pro",
  dodo_product_id: "dodo_pro_monthly",
  name: "Pro",
  amount: 2000,
  currency: "USD",
  duration: "monthly" as const,
  features: ["Unlimited chat", "Workflows"],
  is_active: true,
  created_at: "",
  updated_at: "",
};

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({ plans: [PRO_PLAN] }),
}));

import { PaywallModal } from "@/features/pricing/components/PaywallModal";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("PaywallModal", () => {
  beforeEach(() => {
    usePaywallModalStore.setState({ open: false, offer: null });
    isPaid = false;
    isSubscriptionStatusLoading = false;
    vi.clearAllMocks();
  });

  it("renders non-dismissible with a checkout CTA when open", async () => {
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).not.toBeNull();

    // HeroUI's default close (×) button is hidden — the only exits are
    // subscribe and the quiet logout link.
    expect(screen.queryByRole("button", { name: /close/i })).toBeNull();

    expect(
      screen.getByRole("button", { name: /subscribe to gaia pro/i }),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: /log out/i })).not.toBeNull();
  });

  it("shows the discount banner only when a discount code is present", async () => {
    usePaywallModalStore.getState().openModal({
      checkoutUrl: null,
      discountCode: "LAUNCH20",
    });
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("LAUNCH20")).not.toBeNull();
  });

  it("does not render a discount banner when no offer is set", async () => {
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.queryByText(/at checkout/i)).toBeNull();
  });

  it("starts checkout for the Pro monthly plan, carrying the offer's discount code", async () => {
    usePaywallModalStore.getState().openModal({
      checkoutUrl: null,
      discountCode: "LAUNCH20",
    });
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    fireEvent.click(
      screen.getByRole("button", { name: /subscribe to gaia pro/i }),
    );

    expect(createSubscriptionAndRedirect).toHaveBeenCalledWith(
      "dodo_pro_monthly",
      "LAUNCH20",
    );
  });

  it("logs out via the quiet text link, not by closing the modal", async () => {
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: /log out/i }));

    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("auto-closes when the subscription status resolves to paid while open (cold-cache race guard)", async () => {
    usePaywallModalStore.getState().openModal();
    const { rerender } = render(<PaywallModal />);
    await screen.findByRole("dialog");

    // Subscription-status query resolves to paid — nothing else in the app
    // ever calls closeModal, so the modal must close itself here or a Pro
    // user is trapped behind it forever.
    isPaid = true;
    rerender(<PaywallModal />);

    await waitFor(() => {
      expect(usePaywallModalStore.getState().open).toBe(false);
    });
  });

  it("does not auto-close while the subscription-status query is still loading", async () => {
    isSubscriptionStatusLoading = true;
    usePaywallModalStore.getState().openModal();
    const { rerender } = render(<PaywallModal />);
    await screen.findByRole("dialog");

    // isPaid flips true, but isLoading is still true this render — the
    // resolution isn't trustworthy yet, so the modal must not close.
    isPaid = true;
    rerender(<PaywallModal />);

    expect(usePaywallModalStore.getState().open).toBe(true);
  });
});
