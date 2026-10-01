// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// The dismissible mode's HeroUI Tabs measure themselves via ResizeObserver,
// which jsdom doesn't implement.
class MockResizeObserver {
  observe() {
    // no-op: jsdom has no layout to observe
  }
  unobserve() {
    // no-op: jsdom has no layout to observe
  }
  disconnect() {
    // no-op: jsdom has no layout to observe
  }
}

const openCheckoutOverlay = vi.fn();
const logout = vi.fn();

let isPaid = false;
let isSubscriptionStatusUnknown = false;
let checkoutPhase = "idle";
let hasEverSubscribed: boolean | undefined;

let pathname = "/c";
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => pathname,
}));

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
    hasEverSubscribed,
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

// The dismissible mode embeds the plan picker, which drags in the router,
// the user session and checkout. Those are PricingCards' own tests to run —
// here only the modal shell is under test.
vi.mock("@/features/pricing/components/PricingCards", () => ({
  PricingCards: () => <div data-testid="pricing-cards" />,
}));

import { UpgradeModal } from "@/features/pricing/components/UpgradeModal";
import { trackEvent } from "@/lib/analytics";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

describe("UpgradeModal", () => {
  beforeAll(() => {
    (
      globalThis as unknown as { ResizeObserver: typeof MockResizeObserver }
    ).ResizeObserver = MockResizeObserver;
  });

  beforeEach(() => {
    useUpgradeModalStore.setState({
      open: false,
      offer: null,
      dismissible: false,
      source: null,
    });
    isPaid = false;
    isSubscriptionStatusUnknown = false;
    checkoutPhase = "idle";
    hasEverSubscribed = false;
    pathname = "/c";
    vi.clearAllMocks();
  });

  it("renders non-dismissible with a checkout CTA when open", async () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

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
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { dismissible: true, source: "sidebar" });
    render(<UpgradeModal />);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).not.toBeNull();

    // The close (×) button is shown, and the logout link is redundant next
    // to it, so it's dropped in this mode.
    expect(screen.getByRole("button", { name: /close/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /log out/i })).toBeNull();
  });

  it("clears store state when dismissed via the close button (voluntary upgrade entry points)", async () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { dismissible: true, source: "sidebar" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: /close/i }));

    await waitFor(() => {
      expect(useUpgradeModalStore.getState().open).toBe(false);
    });
    expect(useUpgradeModalStore.getState().dismissible).toBe(false);
  });

  it("shows the discount banner only when a discount code is present", async () => {
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: "LAUNCH20" }, { source: "api_402" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("LAUNCH20")).not.toBeNull();
  });

  it("does not render a discount banner when no offer is set", async () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.queryByText(/at checkout/i)).toBeNull();
  });

  it("opens the embedded overlay for Pro monthly instead of redirecting away", async () => {
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: "LAUNCH20" }, { source: "api_402" });
    render(<UpgradeModal />);

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
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("GAIA is paid only")).not.toBeNull();
    expect(screen.queryByText(/your subscription ended/i)).toBeNull();
  });

  it("shows the lapsed copy to a user who has subscribed before", async () => {
    hasEverSubscribed = true;
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("Your subscription ended")).not.toBeNull();
    expect(
      screen.getByText(/pick up right where you left off/i),
    ).not.toBeNull();
    expect(screen.queryByText("GAIA is paid only")).toBeNull();
  });

  it("keeps the migration copy while the status is still unknown", async () => {
    hasEverSubscribed = undefined;
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText("GAIA is paid only")).not.toBeNull();
  });

  it("carries no refund or tax footnote under the CTA", async () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.queryByText(/Cancel within/)).toBeNull();
    expect(screen.queryByText(/taxes/i)).toBeNull();
  });

  it("does not label the feature list with the plan name", async () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.queryByText("Pro")).toBeNull();
  });

  it("renders nothing on the onboarding route, where the wizard owns payment", () => {
    pathname = "/onboarding";
    try {
      useUpgradeModalStore
        .getState()
        .openModal(undefined, { source: "composer_submit" });
      render(<UpgradeModal />);
      expect(screen.queryByRole("dialog")).toBeNull();
    } finally {
      pathname = "/c";
    }
  });

  it("replaces the CTA with a confirming state once the overlay closes", async () => {
    checkoutPhase = "confirming";
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText(/confirming your payment/i)).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: /subscribe to gaia pro/i }),
    ).toBeNull();
    expect(screen.queryByText(/taking longer than expected/i)).toBeNull();
  });

  it("admits the delay once confirmation passes its visible budget", async () => {
    checkoutPhase = "timeout";
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    expect(screen.getByText(/taking longer than expected/i)).not.toBeNull();
  });

  it("attributes the checkout to the paywall without emitting a client checkout event", () => {
    // The API owns payment:checkout_started now — it fires after the session
    // actually exists and carries the same `source` this click passes down.
    // Any client capture here would be a rival event for one user action.
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });
    render(<UpgradeModal />);

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
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: "LAUNCH20" }, { source: "api_402" });
    const { rerender } = render(<UpgradeModal />);
    rerender(<UpgradeModal />);

    const impressions = vi
      .mocked(trackEvent)
      .mock.calls.filter(([event]) => event === "paywall:modal_viewed");

    expect(impressions).toHaveLength(1);
    expect(impressions[0][1]).toEqual({
      dismissible: false,
      has_discount_code: true,
      source: "api_402",
    });
  });

  it("says which surface produced the wall", () => {
    // Without this the metric can only say a wall was shown, never where the
    // paid-only gate actually bites.
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "workflow_activation" });
    render(<UpgradeModal />);

    expect(trackEvent).toHaveBeenCalledWith(
      "paywall:modal_viewed",
      expect.objectContaining({ source: "workflow_activation" }),
    );
  });

  it("captures no impression while the paywall is closed", () => {
    render(<UpgradeModal />);

    expect(trackEvent).not.toHaveBeenCalledWith(
      "paywall:modal_viewed",
      expect.anything(),
    );
  });

  it("captures no impression on the route where it renders nothing", () => {
    // The wizard owns payment on its own stage, so this modal returns null
    // there. An impression for a wall that never reached the screen is the
    // one thing this event exists not to do.
    pathname = "/onboarding";
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: "LAUNCH20" }, { source: "api_402" });

    const { container } = render(<UpgradeModal />);

    expect(container.firstChild).toBeNull();
    expect(trackEvent).not.toHaveBeenCalledWith(
      "paywall:modal_viewed",
      expect.anything(),
    );
  });

  it("logs out via the quiet text link, not by closing the modal", async () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    render(<UpgradeModal />);

    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: /log out/i }));

    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("auto-closes when the subscription status resolves to paid while open (cold-cache race guard)", async () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    const { rerender } = render(<UpgradeModal />);
    await screen.findByRole("dialog");

    // Subscription-status query resolves to paid — nothing else in the app
    // ever calls closeModal, so the modal must close itself here or a Pro
    // user is trapped behind it forever.
    isPaid = true;
    rerender(<UpgradeModal />);

    await waitFor(() => {
      expect(useUpgradeModalStore.getState().open).toBe(false);
    });
  });

  it("does not auto-close while the subscription status is still unknown", async () => {
    isSubscriptionStatusUnknown = true;
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });
    const { rerender } = render(<UpgradeModal />);
    await screen.findByRole("dialog");

    // isPaid flips true, but isUnknown is still true this render — the
    // resolution isn't trustworthy yet, so the modal must not close.
    isPaid = true;
    rerender(<UpgradeModal />);

    expect(useUpgradeModalStore.getState().open).toBe(true);
  });
});
