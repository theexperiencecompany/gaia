// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let isPaid = false;
let isUnknown = false;
const { refetch } = vi.hoisted(() => ({
  refetch: vi.fn().mockResolvedValue({ plan_type: "free" }),
}));

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isUnknown, hasEverSubscribed: false }),
}));

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: { getSubscriptionStatus: refetch },
}));

import { useClearPaywallWhenPaid } from "@/features/pricing/hooks/useClearPaywallWhenPaid";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

function withQueryClient({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

const render = () =>
  renderHook(() => useClearPaywallWhenPaid(), { wrapper: withQueryClient });

describe("useClearPaywallWhenPaid", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useUpgradeModalStore.setState({
      open: false,
      offer: null,
      dismissible: false,
      source: null,
    });
    isPaid = false;
    isUnknown = false;
    refetch.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("takes down an undismissable wall the moment the subscription is real", () => {
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });
    const { rerender } = render();

    isPaid = true;
    rerender();

    expect(useUpgradeModalStore.getState().open).toBe(false);
  });

  it("does not act on a plan status that has not resolved yet", () => {
    isUnknown = true;
    isPaid = true;
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });

    render();

    expect(useUpgradeModalStore.getState().open).toBe(true);
  });

  it("keeps asking the server while the wall stands", () => {
    // The wall outlives the checkout that lifts it: desktop sends the user to
    // a browser to subscribe, and the plan query (a minute stale, no refetch
    // on focus) never re-reads — without this the wall survives a restart.
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });
    render();

    vi.advanceTimersByTime(60_000);

    // A poll, not the user: the server must not count an idle tab as active.
    expect(refetch).toHaveBeenCalledWith({ background: true });
  });

  it("asks for nothing while no wall is up", () => {
    render();

    vi.advanceTimersByTime(60_000);

    expect(refetch).not.toHaveBeenCalled();
  });

  it("stops asking once the answer is yes", () => {
    isPaid = true;
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });

    render();
    vi.advanceTimersByTime(60_000);

    expect(refetch).not.toHaveBeenCalled();
  });
});
