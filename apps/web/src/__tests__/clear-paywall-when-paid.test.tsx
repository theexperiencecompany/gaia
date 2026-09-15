// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let isPaid = false;
let isUnknown = false;
const refetch = vi.fn();

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isUnknown, hasEverSubscribed: false }),
}));

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  useUserSubscriptionStatus: () => ({ refetch }),
}));

import { useClearPaywallWhenPaid } from "@/features/pricing/hooks/useClearPaywallWhenPaid";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

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
    const { rerender } = renderHook(() => useClearPaywallWhenPaid());

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

    renderHook(() => useClearPaywallWhenPaid());

    expect(useUpgradeModalStore.getState().open).toBe(true);
  });

  it("keeps asking the server while the wall stands", () => {
    // The wall outlives the checkout that lifts it: the desktop popup sends
    // the user to subscribe in their browser, and nothing in that window
    // would ever re-read the plan — the query is a minute stale and never
    // refetches on focus. Without this the wall survives until a restart.
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });
    renderHook(() => useClearPaywallWhenPaid());

    vi.advanceTimersByTime(60_000);

    expect(refetch).toHaveBeenCalled();
  });

  it("asks for nothing while no wall is up", () => {
    renderHook(() => useClearPaywallWhenPaid());

    vi.advanceTimersByTime(60_000);

    expect(refetch).not.toHaveBeenCalled();
  });

  it("stops asking once the answer is yes", () => {
    isPaid = true;
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });

    renderHook(() => useClearPaywallWhenPaid());
    vi.advanceTimersByTime(60_000);

    expect(refetch).not.toHaveBeenCalled();
  });
});
