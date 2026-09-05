// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let search = "";
const verifyPayment = vi.fn(async () => ({ payment_completed: false }));
const refetchSubscription = vi.fn(async () => undefined);

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid: false, isUnknown: false }),
}));
vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({ verifyPayment, refetchSubscription }),
}));

import { useCheckoutReturn } from "@/features/onboarding/hooks/useCheckoutReturn";

describe("useCheckoutReturn", () => {
  beforeEach(() => {
    verifyPayment.mockClear();
    vi.useRealTimers();
  });

  it("reads a declined charge off Dodo's return URL and skips verification", () => {
    search = "checkout=returned&subscription_id=sub_1&status=failed";
    const { result } = renderHook(() => useCheckoutReturn());
    expect(result.current.returned).toBe(true);
    expect(result.current.failed).toBe(true);
    expect(result.current.timedOut).toBe(false);
    expect(verifyPayment).not.toHaveBeenCalled();
  });

  it("verifies a returned checkout and gives up after the budget", () => {
    vi.useFakeTimers();
    search = "checkout=returned&subscription_id=sub_1&status=succeeded";
    const { result } = renderHook(() => useCheckoutReturn());
    expect(result.current.failed).toBe(false);
    expect(verifyPayment).toHaveBeenCalledWith("sub_1");
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(result.current.isLate).toBe(true);
    expect(result.current.timedOut).toBe(false);
    act(() => {
      vi.advanceTimersByTime(90_000);
    });
    expect(result.current.timedOut).toBe(true);
  });

  it("strips Dodo's query from the address bar as soon as it is read", () => {
    search = "checkout=returned&status=failed";
    window.history.replaceState(null, "", `/onboarding?${search}`);
    const spy = vi.spyOn(window.history, "replaceState");
    const { result } = renderHook(() => useCheckoutReturn());
    expect(spy).toHaveBeenCalledWith(null, "", "/onboarding");
    // The outcome survives the strip: it lives in state, not in the URL.
    expect(result.current.failed).toBe(true);
    spy.mockRestore();
  });

  it("retry leaves the confirming state without touching the URL again", () => {
    search = "checkout=returned&status=failed";
    const { result } = renderHook(() => useCheckoutReturn());
    act(() => result.current.retry());
    expect(result.current.returned).toBe(false);
    expect(result.current.failed).toBe(false);
  });
});
