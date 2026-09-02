// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openExternal = vi.fn();

vi.mock("@/hooks/useElectron", () => ({
  useElectron: () => ({ openExternal }),
}));

import PopupPaywallNotice from "@/features/desktop-popup/components/PopupPaywallNotice";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("PopupPaywallNotice", () => {
  beforeEach(() => {
    usePaywallModalStore.setState({
      open: false,
      offer: null,
      dismissible: false,
    });
    openExternal.mockReset();
  });

  it("renders nothing while the user is not blocked", () => {
    const { container } = render(<PopupPaywallNotice />);

    expect(container.firstChild).toBeNull();
  });

  it("surfaces the block in the popup once a 402 opens the paywall", () => {
    // The whole point of the popup fix: before this, a 402 flipped this store
    // in the composer window and nothing in the (desktop) tree rendered it, so
    // the user's send vanished in silence.
    usePaywallModalStore.getState().openModal({
      checkoutUrl: "https://checkout.dodo.test/abc",
      discountCode: "LAUNCH20",
      message: "GAIA is a paid product.",
    });
    render(<PopupPaywallNotice />);

    expect(screen.getByText(/GAIA is a paid product\./i)).not.toBeNull();
    expect(screen.getByText("LAUNCH20")).not.toBeNull();
  });

  it("opens the 402's own checkout link in the browser, not in the popup window", () => {
    usePaywallModalStore.getState().openModal({
      checkoutUrl: "https://checkout.dodo.test/abc",
      discountCode: null,
    });
    render(<PopupPaywallNotice />);

    fireEvent.click(screen.getByRole("button", { name: /subscribe/i }));

    expect(openExternal).toHaveBeenCalledWith("https://checkout.dodo.test/abc");
  });

  it("falls back to the pricing page when Dodo minted no checkout link", () => {
    // A paywall response never fails just because the checkout provider is
    // down — the block still stands, so the CTA must still lead somewhere.
    usePaywallModalStore.getState().openModal({
      checkoutUrl: null,
      discountCode: null,
    });
    render(<PopupPaywallNotice />);

    fireEvent.click(screen.getByRole("button", { name: /subscribe/i }));

    expect(openExternal).toHaveBeenCalledWith(
      `${window.location.origin}/pricing`,
    );
  });
});
