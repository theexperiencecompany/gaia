// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CheckoutPhase } from "@/features/pricing/stores/checkoutOverlayStore";

let search = "";
let checkoutPhase: CheckoutPhase = "idle";
const confirmReturnedCheckout = vi.fn();
const clearError = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/features/pricing/hooks/useDodoPayments", () => ({
  useDodoPayments: () => ({
    checkoutPhase,
    confirmReturnedCheckout,
    clearError,
  }),
}));

import { useCheckoutReturn } from "@/features/onboarding/hooks/useCheckoutReturn";

describe("useCheckoutReturn", () => {
  beforeEach(() => {
    confirmReturnedCheckout.mockClear();
    clearError.mockClear();
    checkoutPhase = "idle";
  });

  it("reads a declined charge off Dodo's return URL and never starts a wait", () => {
    search = "checkout=returned&subscription_id=sub_1&status=failed";
    const { result } = renderHook(() => useCheckoutReturn());
    expect(result.current.returned).toBe(true);
    expect(result.current.failed).toBe(true);
    expect(result.current.timedOut).toBe(false);
    expect(confirmReturnedCheckout).not.toHaveBeenCalled();
  });

  it("hands a returned checkout to the store's one confirmation loop", () => {
    search = "checkout=returned&subscription_id=sub_1&status=succeeded";
    const { result } = renderHook(() => useCheckoutReturn());
    expect(result.current.failed).toBe(false);
    expect(confirmReturnedCheckout).toHaveBeenCalledWith("sub_1");
  });

  it("reads late and given-up straight off the store's phase", () => {
    search = "checkout=returned&subscription_id=sub_1&status=succeeded";
    checkoutPhase = "timeout";
    const late = renderHook(() => useCheckoutReturn());
    expect(late.result.current.isLate).toBe(true);
    expect(late.result.current.timedOut).toBe(false);

    checkoutPhase = "unconfirmed";
    const gaveUp = renderHook(() => useCheckoutReturn());
    expect(gaveUp.result.current.timedOut).toBe(true);
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

  it("keeps the locale prefix it was returned to", () => {
    // Dodo returns a French user to /fr/onboarding. Rewriting that to
    // /onboarding drops them into English on the next reload or bookmark,
    // mid-payment.
    search = "checkout=returned&status=failed";
    window.history.replaceState(null, "", `/fr/onboarding?${search}`);
    const spy = vi.spyOn(window.history, "replaceState");

    renderHook(() => useCheckoutReturn());

    expect(spy).toHaveBeenCalledWith(null, "", "/fr/onboarding");
    spy.mockRestore();
  });

  it("strips only Dodo's params, leaving the rest of the query alone", () => {
    search =
      "ref=newsletter&checkout=returned&subscription_id=sub_1&status=succeeded";
    window.history.replaceState(null, "", `/onboarding?${search}`);
    const spy = vi.spyOn(window.history, "replaceState");

    renderHook(() => useCheckoutReturn());

    expect(spy).toHaveBeenCalledWith(null, "", "/onboarding?ref=newsletter");
    spy.mockRestore();
  });

  it("retry settles the store and leaves the confirming state without touching the URL again", () => {
    search = "checkout=returned&status=failed";
    const { result } = renderHook(() => useCheckoutReturn());
    act(() => result.current.retry());
    expect(clearError).toHaveBeenCalledOnce();
    expect(result.current.returned).toBe(false);
    expect(result.current.failed).toBe(false);
  });
});
