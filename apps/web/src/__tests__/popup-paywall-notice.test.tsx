// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openExternal = vi.fn();
const createCheckoutSession = vi.fn();

vi.mock("@/hooks/useElectron", () => ({
  useElectron: () => ({ openExternal }),
}));

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: {
    createCheckoutSession: (...args: unknown[]) =>
      createCheckoutSession(...args),
  },
}));

import PopupPaywallNotice from "@/features/desktop-popup/components/PopupPaywallNotice";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

describe("PopupPaywallNotice", () => {
  beforeEach(() => {
    useUpgradeModalStore.setState({
      open: false,
      offer: null,
      dismissible: false,
      source: null,
    });
    openExternal.mockReset();
    createCheckoutSession.mockReset();
    createCheckoutSession.mockResolvedValue({
      subscription_id: "sub_1",
      payment_link: "https://checkout.dodo.test/abc",
      status: "payment_link_created",
    });
  });

  it("renders nothing while the user is not blocked", () => {
    const { container } = render(<PopupPaywallNotice />);

    expect(container.firstChild).toBeNull();
  });

  it("surfaces the block in the popup once a 402 opens the paywall", () => {
    // The whole point of the popup fix: before this, a 402 flipped this store
    // in the composer window and nothing in the (desktop) tree rendered it, so
    // the user's send vanished in silence.
    useUpgradeModalStore
      .getState()
      .openModal(
        { discountCode: "LAUNCH20", message: "GAIA is a paid product." },
        { source: "api_402" },
      );
    render(<PopupPaywallNotice />);

    expect(screen.getByText(/GAIA is a paid product\./i)).not.toBeNull();
    expect(screen.getByText("LAUNCH20")).not.toBeNull();
  });

  it("mints the checkout only when the user asks for it, and opens it in the browser", async () => {
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });
    render(<PopupPaywallNotice />);

    // Nothing is minted by the wall going up — that is what turned one
    // blocked screen into a pile of abandoned Dodo sessions.
    expect(createCheckoutSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /subscribe/i }));

    await waitFor(() =>
      expect(openExternal).toHaveBeenCalledWith(
        "https://checkout.dodo.test/abc",
      ),
    );
  });

  it("falls back to the pricing page when the session cannot be minted", async () => {
    // A paywall never fails just because the checkout provider is down — the
    // block still stands, so the CTA must still lead somewhere.
    createCheckoutSession.mockRejectedValue(new Error("Dodo is down"));
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });
    render(<PopupPaywallNotice />);

    fireEvent.click(screen.getByRole("button", { name: /subscribe/i }));

    await waitFor(() =>
      expect(openExternal).toHaveBeenCalledWith(
        `${window.location.origin}/pricing`,
      ),
    );
  });
});
