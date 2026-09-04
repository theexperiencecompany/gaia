// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let isPaid = false;
let isUnknown = false;
let hasEverSubscribed: boolean | undefined = false;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isUnknown, hasEverSubscribed }),
}));

import { PaywallNotice } from "@/features/chat/components/composer/PaywallNotice";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("PaywallNotice", () => {
  beforeEach(() => {
    isPaid = false;
    isUnknown = false;
    hasEverSubscribed = false;
    usePaywallModalStore.setState({ open: false, offer: null });
  });

  it("tells a lapsed subscriber to resubscribe, not that the rules changed", () => {
    hasEverSubscribed = true;
    render(<PaywallNotice />);

    expect(screen.getByText(/your subscription ended/i)).not.toBeNull();
    expect(screen.queryByText(/GAIA is paid only right now/i)).toBeNull();
    expect(
      screen.getByRole("button", { name: /^resubscribe$/i }),
    ).not.toBeNull();
  });

  it("renders the upgrade notice for a loaded free (non-subscribed) user", () => {
    render(<PaywallNotice />);

    expect(screen.getByText(/GAIA is paid only right now/i)).not.toBeNull();
    expect(screen.getByRole("button", { name: /subscribe/i })).not.toBeNull();
  });

  it("does not render while the subscription status is still unknown", () => {
    isUnknown = true;
    const { container } = render(<PaywallNotice />);

    expect(container.firstChild).toBeNull();
  });

  it("does not render for a paid user", () => {
    isPaid = true;
    const { container } = render(<PaywallNotice />);

    expect(container.firstChild).toBeNull();
  });

  it("opens the paywall modal store when the upgrade button is pressed", () => {
    render(<PaywallNotice />);

    fireEvent.click(screen.getByRole("button", { name: /subscribe/i }));

    expect(usePaywallModalStore.getState().open).toBe(true);
    // Enforcement — the composer's paywall notice is itself a consequence of
    // being blocked, so its "Upgrade to Pro" must not open a dismissible
    // paywall the user could close their way past.
    expect(usePaywallModalStore.getState().dismissible).toBe(false);
  });
});
