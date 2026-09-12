import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.fn();

vi.mock("@/lib/api/client", () => ({
  apiauth: { request: (...args: unknown[]) => request(...args) },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { API_REQUEST_FAILED: "api:request_failed" },
  trackEvent: vi.fn(),
}));

import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";

/** What the interceptor hands back for a 402 it recognised and acted on. */
const handledPaywall = () =>
  Object.assign(new Error("Request failed with status code 402"), {
    handled: true,
    response: {
      status: 402,
      data: { code: "subscription_required", message: "Subscribe" },
    },
  });

/** A 402 the interceptor deliberately left unhandled — a shape it does not
 *  recognise, or a request made from a page that mounts no interceptor. */
const unhandledPaywall = () =>
  Object.assign(new Error("Request failed with status code 402"), {
    response: { status: 402, data: { message: "Wallet balance too low" } },
  });

describe("apiService error toasts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("stays quiet for a 402 the paywall already surfaced", async () => {
    request.mockRejectedValue(handledPaywall());

    await expect(apiService.get("/gated")).rejects.toThrow();

    expect(toast.error).not.toHaveBeenCalled();
  });

  it("toasts a 402 nobody handled instead of swallowing it", async () => {
    // The interceptor returns `handled = false` on purpose for a body that is
    // not the subscription_required shape, so that the request surfaces here
    // rather than becoming a click that does nothing at all.
    request.mockRejectedValue(unhandledPaywall());

    await expect(apiService.get("/gated")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("Wallet balance too low");
  });
});
