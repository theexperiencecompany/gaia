// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openCheckoutOverlay = vi.fn();
const logout = vi.fn();

let isPaid = false;
let isSubscriptionStatusUnknown = false;
let checkoutPhase = "idle";
let hasEverSubscribed: boolean | undefined;

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    SUBSCRIPTION_CHECKOUT_STARTED: "subscription:checkout_started",
    PAYWALL_MODAL_VIEWED: "paywall:modal_viewed",
  },
  trackEvent: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useLogout", () => ({
  useLogout: () => ({ logout }),
}));

vi.mock("@/features/pricing/hooks/useDodoPayments", () => ({
  useDodoPayments: () => ({
    openCheckoutOverlay,
    checkoutPhase,
    isLoading: false,
    error: null,
    clearError: vi.fn(),
  }),
}));

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({
    isPaid,
    isUnknown: isSubscriptionStatusUnknown,
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
  useUserSubscriptionStatus: () => ({
    data:
      hasEverSubscribed === undefined
        ? undefined
        : { has_ever_subscribed: hasEverSubscribed },
  }),
}));

import { PaywallModal } from "@/features/pricing/components/PaywallModal";
import { trackEvent } from "@/lib/analytics";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("PaywallModal", () => {
  beforeEach(() => {
    usePaywallModalStore.setState({
      open: false,
      offer: null,
      dismissible: false,
    });
    isPaid = false;
    isSubscriptionStatusUnknown = false;
    checkoutPhase = "idle";
    hasEverSubscribed = false;
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

  it("renders dismissible with a close button and no logout link when opened dismissible (voluntary upgrade entry points)", async () => {
    usePaywallModalStore.getState().openModal(undefined, { dismissible: true });
    render(<PaywallModal />);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).not.toBeNull();

    // The close (×) button is shown, and the logout link is redundant next
    // to it, so it's dropped in this mode.
    expect(screen.getByRole("button", { name: /close/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /log out/i })).toBeNull();
  });

  it("clears store state when dismissed via the close button (voluntary upgrade entry points)", async () => {
    usePaywallModalStore.getState().openModal(undefined, { dismissible: true });
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: /close/i }));

    await waitFor(() => {
      expect(usePaywallModalStore.getState().open).toBe(false);
    });
    expect(usePaywallModalStore.getState().dismissible).toBe(false);
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

  it("opens the embedded overlay for Pro monthly instead of redirecting away", async () => {
    usePaywallModalStore.getState().openModal({
      checkoutUrl: null,
      discountCode: "LAUNCH20",
    });
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    fireEvent.click(
      screen.getByRole("button", { name: /subscribe to gaia pro/i }),
    );

    // No discount code from the client: the server pre-applies
    // PAYWALL_DISCOUNT_CODE inside create_pro_checkout, so passing it here too
    // would be a second source of truth for the same code.
    expect(openCheckoutOverlay).toHaveBeenCalledWith("monthly", {
      source: "paywall_modal",
    });
  });

  it("shows the migration copy to a user who has never subscribed", async () => {
    hasEverSubscribed = false;
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("GAIA is Pro-only")).not.toBeNull();
    expect(screen.queryByText(/your subscription ended/i)).toBeNull();
  });

  it("shows the lapsed copy to a user who has subscribed before", async () => {
    hasEverSubscribed = true;
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("Your subscription ended")).not.toBeNull();
    expect(
      screen.getByText(/pick up right where you left off/i),
    ).not.toBeNull();
    expect(screen.queryByText("GAIA is Pro-only")).toBeNull();
  });

  it("keeps the migration copy while the status is still unknown", async () => {
    hasEverSubscribed = undefined;
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("GAIA is Pro-only")).not.toBeNull();
  });

  it("shows the 7-day cancellation line next to the CTA", async () => {
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("Cancel within 7 days.")).not.toBeNull();
  });

  it("replaces the CTA with a confirming state once the overlay closes", async () => {
    checkoutPhase = "confirming";
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText(/confirming your payment/i)).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: /subscribe to gaia pro/i }),
    ).toBeNull();
    expect(screen.queryByText(/taking longer than expected/i)).toBeNull();
  });

  it("admits the delay once confirmation passes its visible budget", async () => {
    checkoutPhase = "timeout";
    usePaywallModalStore.getState().openModal();
    render(<PaywallModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText(/taking longer than expected/i)).not.toBeNull();
  });

  it("attributes the checkout to the paywall without emitting a second checkout event", () => {
    // The hook is the single emitter for subscription:checkout_started; a
    // capture here too would double-count every gate-driven checkout against
    // the pricing-page ones that only fire inside the hook.
    usePaywallModalStore.getState().openModal({
      checkoutUrl: null,
      discountCode: null,
    });
    render(<PaywallModal />);

    fireEvent.click(
      screen.getByRole("button", { name: /subscribe to gaia pro/i }),
    );

    expect(trackEvent).not.toHaveBeenCalledWith(
      "subscription:checkout_started",
      expect.anything(),
    );
    expect(openCheckoutOverlay).toHaveBeenCalledWith(
      "monthly",
      expect.objectContaining({ source: "paywall_modal" }),
    );
  });

  it("captures one paywall impression per open, with the offer's shape", () => {
    usePaywallModalStore.getState().openModal({
      checkoutUrl: "https://checkout.dodo.test/abc",
      discountCode: "LAUNCH20",
    });
    const { rerender } = render(<PaywallModal />);
    rerender(<PaywallModal />);

    const impressions = vi
      .mocked(trackEvent)
      .mock.calls.filter(([event]) => event === "paywall:modal_viewed");

    expect(impressions).toHaveLength(1);
    expect(impressions[0][1]).toEqual({
      dismissible: false,
      has_checkout_url: true,
      has_discount_code: true,
    });
  });

  it("captures no impression while the paywall is closed", () => {
    render(<PaywallModal />);

    expect(trackEvent).not.toHaveBeenCalledWith(
      "paywall:modal_viewed",
      expect.anything(),
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

  it("does not auto-close while the subscription status is still unknown", async () => {
    isSubscriptionStatusUnknown = true;
    usePaywallModalStore.getState().openModal();
    const { rerender } = render(<PaywallModal />);
    await screen.findByRole("dialog");

    // isPaid flips true, but isUnknown is still true this render — the
    // resolution isn't trustworthy yet, so the modal must not close.
    isPaid = true;
    rerender(<PaywallModal />);

    expect(usePaywallModalStore.getState().open).toBe(true);
  });
});
