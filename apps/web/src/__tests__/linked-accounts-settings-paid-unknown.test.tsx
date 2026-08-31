// @vitest-environment jsdom
//
// Regression coverage for the "paying user sees free-tier UI / gets blocked"
// bug in LinkedAccountsSettings: the premium-platform gate (iMessage) read
// `subscriptionStatus?.is_subscribed` directly off the raw (possibly
// disabled/never-fetched) subscription-status query. A cold cache read that
// as `undefined` — falsy — so a paying user reloading mid-fetch saw the
// "Pro" badge and had their connect attempt redirected to the paywall
// instead of proceeding. The fix routes through `useIsPaid()`: never show
// the "Pro" badge, and never block the connect action, while unknown.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let isPaid = false;
let isUnknown = false;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isUnknown }),
}));

const openPricingModal = vi.fn();
vi.mock("@/stores/pricingModalStore", () => ({
  usePricingModalStore: (selector: (s: unknown) => unknown) =>
    selector({ openModal: openPricingModal }),
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    BOT_CONNECTED: "bot:connected",
    BOT_DISCONNECTED: "bot:disconnected",
  },
  trackEvent: vi.fn(),
}));

vi.mock("@/lib/api/service", () => ({
  apiService: {
    get: vi.fn().mockResolvedValue({ platform_links: {} }),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

import LinkedAccountsSettings from "@/features/settings/components/LinkedAccountsSettings";

/** Locates the settings row for a given platform label and returns it as a
 * Testing Library `within` scope, so assertions never risk matching the
 * wrong platform's badge/button. */
async function findPlatformRow(label: string) {
  const labelEl = await screen.findByText(label);
  // SettingsRow renders label + children (badge, Connect button) as
  // siblings two levels up from the label <p>.
  const row = labelEl.closest("div.flex.px-4") as HTMLElement;
  expect(row).not.toBeNull();
  return within(row);
}

describe("LinkedAccountsSettings — iMessage (premium) gate vs. plan status unknown", () => {
  beforeEach(() => {
    isPaid = false;
    isUnknown = false;
    openPricingModal.mockReset();
  });

  it("shows the Pro badge and paywalls the connect attempt for a known-free user", async () => {
    render(<LinkedAccountsSettings />);
    const row = await findPlatformRow("iMessage");

    expect(row.getByText("Pro")).not.toBeNull();
    fireEvent.click(row.getByRole("button", { name: "Connect" }));
    expect(openPricingModal).toHaveBeenCalledTimes(1);
  });

  it("does not show the Pro badge and does not paywall the connect attempt for a paid user", async () => {
    isPaid = true;
    render(<LinkedAccountsSettings />);
    const row = await findPlatformRow("iMessage");

    expect(row.queryByText("Pro")).toBeNull();
    fireEvent.click(row.getByRole("button", { name: "Connect" }));
    expect(openPricingModal).not.toHaveBeenCalled();
  });

  it("does not show the Pro badge and lets the connect attempt proceed while the subscription status is still unknown", async () => {
    isPaid = false;
    isUnknown = true;
    render(<LinkedAccountsSettings />);
    const row = await findPlatformRow("iMessage");

    // Before the fix, `subscriptionStatus?.is_subscribed` read as
    // `undefined` in this exact window — falsy — so the badge showed and
    // the connect attempt below would have opened the pricing modal for a
    // possibly-paid user.
    expect(row.queryByText("Pro")).toBeNull();
    fireEvent.click(row.getByRole("button", { name: "Connect" }));
    expect(openPricingModal).not.toHaveBeenCalled();
  });
});
