// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let isPaid = false;
let isLoading = false;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isLoading }),
}));

import { PaywallNotice } from "@/features/chat/components/composer/PaywallNotice";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("PaywallNotice", () => {
  beforeEach(() => {
    isPaid = false;
    isLoading = false;
    usePaywallModalStore.setState({ open: false, offer: null });
  });

  it("renders the upgrade notice for a loaded free (non-subscribed) user", () => {
    render(<PaywallNotice />);

    expect(screen.getByText(/GAIA is paid-only right now/i)).not.toBeNull();
    expect(
      screen.getByRole("button", { name: /upgrade to pro/i }),
    ).not.toBeNull();
  });

  it("does not render while the subscription-status query is still loading", () => {
    isLoading = true;
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

    fireEvent.click(screen.getByRole("button", { name: /upgrade to pro/i }));

    expect(usePaywallModalStore.getState().open).toBe(true);
  });
});
