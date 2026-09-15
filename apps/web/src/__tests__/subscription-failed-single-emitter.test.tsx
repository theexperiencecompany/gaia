// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createCheckoutSession = vi.fn();
const createSubscription = vi.fn();

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: {
    createCheckoutSession: (...args: unknown[]) =>
      createCheckoutSession(...args),
    createSubscription: (...args: unknown[]) => createSubscription(...args),
    getSubscriptionStatus: vi.fn(),
    verifyPayment: vi.fn(),
  },
}));

vi.mock("@/features/pricing/lib/dodoOverlay", () => ({
  openDodoOverlay: vi.fn(),
  closeDodoOverlay: vi.fn(),
}));

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  useUserSubscriptionStatus: () => ({ refetch: vi.fn() }),
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { SUBSCRIPTION_FAILED: "subscription:failed" },
  trackEvent: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

import { useDodoPayments } from "@/features/pricing/hooks/useDodoPayments";
import { trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

/**
 * One user action, one event, emitted from the server. A checkout the API
 * refused is a failure the API already saw and captured; a second capture
 * from here would double-count it. The one client emitter that survives is
 * `useCheckoutReturn`'s, for the outcomes no server ever sees (a declined
 * charge, a webhook that never lands).
 */
describe("subscription:failed has no client emitter for server-seen failures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not double-count a checkout session the server refused", async () => {
    createCheckoutSession.mockRejectedValue(new Error("No Pro plan"));
    const { result } = renderHook(() => useDodoPayments());

    await result.current.openCheckoutOverlay("monthly", {
      source: "paywall_modal",
    });

    expect(toast.error).toHaveBeenCalledWith("No Pro plan");
    expect(trackEvent).not.toHaveBeenCalledWith(
      "subscription:failed",
      expect.anything(),
    );
  });

  it("does not double-count a subscription the server refused", async () => {
    createSubscription.mockRejectedValue(new Error("Plan not available"));
    const { result } = renderHook(() => useDodoPayments());

    await result.current.createSubscriptionAndRedirect("plan_pro", {
      source: "pricing_card",
    });

    expect(toast.error).toHaveBeenCalledWith("Plan not available");
    expect(trackEvent).not.toHaveBeenCalledWith(
      "subscription:failed",
      expect.anything(),
    );
  });
});
