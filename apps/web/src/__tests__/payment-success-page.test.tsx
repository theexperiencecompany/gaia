// @vitest-environment jsdom
/**
 * `/payment/success` — the page every off-page payment rail lands on.
 *
 * Two things are pinned here, both observed broken in a live run:
 *
 * 1. The verification resolves exactly once and always leaves the spinner.
 *    The page ran its verify effect under a `hasVerified` ref while the
 *    effect's cleanup cancelled the only run — so React's StrictMode
 *    double-invoke (the app sets `reactStrictMode: true`) discarded run #1's
 *    result and short-circuited run #2, stranding the user on
 *    "Verifying payment" forever with an active subscription.
 * 2. A user whose onboarding is not finished is sent back into the flow,
 *    where the persisted stage machine resumes at the payment stage — not
 *    dumped into chat with half an onboarding behind them.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const verifyPayment = vi.fn();
const push = vi.fn();
const createSubscriptionAndRedirect = vi.fn();

let onboarding: { completed: boolean } | undefined;
/** Bumped per test to hand the page a fresh `verifyPayment` identity on every
 *  render, reproducing the dependency-driven effect re-run. */
let unstableVerifyIdentity = false;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams("subscription_id=sub_123"),
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ onboarding }),
}));

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({
    plans: [],
    subscriptionStatus: null,
    verifyPayment: unstableVerifyIdentity
      ? (...args: unknown[]) => verifyPayment(...args)
      : verifyPayment,
  }),
}));

// The retry wrapper waits with growing delays between attempts; the page's
// own behaviour is what these tests pin, so verification resolves in one call.
vi.mock("@/features/pricing/utils/verifyPaymentWithRetry", () => ({
  verifyPaymentWithRetry: (verify: () => Promise<unknown>) => verify(),
}));

vi.mock("@/features/pricing/hooks/useDodoPayments", () => ({
  useDodoPayments: () => ({
    createSubscriptionAndRedirect,
    isLoading: false,
  }),
}));

vi.mock("@/features/pricing/components/PaymentBackdrop", () => ({
  PaymentBackdrop: () => null,
}));

vi.mock("@/hooks/ui/useCreateConfetti", () => ({
  default: () => null,
}));

vi.mock("@/features/pricing/components/PostPaymentReceipt", () => ({
  PostPaymentReceipt: () => <div>Receipt printed</div>,
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { SUBSCRIPTION_FAILED: "subscription:failed" },
  trackEvent: vi.fn(),
}));

import PaymentSuccessPage from "@/app/[locale]/(landing)/payment/success/page";
import { trackEvent } from "@/lib/analytics";

describe("PaymentSuccessPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    onboarding = { completed: true };
    unstableVerifyIdentity = false;
    verifyPayment.mockResolvedValue({
      payment_completed: true,
      subscription_id: "sub_123",
    });
  });

  it("leaves the spinner under StrictMode's double-invoked effect", async () => {
    render(
      <StrictMode>
        <PaymentSuccessPage />
      </StrictMode>,
    );

    expect(await screen.findByText("Receipt printed")).toBeDefined();
    expect(screen.queryByText("Verifying payment")).toBeNull();
    // The ref guard exists so the charge is only ever verified once, and the
    // subscription from the return URL rides along so the server can
    // reconcile a dropped webhook.
    expect(verifyPayment).toHaveBeenCalledTimes(1);
    expect(verifyPayment).toHaveBeenCalledWith("sub_123");
  });

  it("leaves the spinner when the verify callback's identity changes mid-flight", async () => {
    // `usePricing` rebuilds `verifyPayment` whenever its own dependencies
    // settle, so a re-render can hand the effect a new identity while the
    // first verification is still in the air.
    let resolveVerify: (value: unknown) => void = () => undefined;
    verifyPayment.mockReturnValue(
      new Promise((resolve) => {
        resolveVerify = resolve;
      }),
    );
    unstableVerifyIdentity = true;

    const { rerender } = render(<PaymentSuccessPage />);
    rerender(<PaymentSuccessPage />);
    resolveVerify({ payment_completed: true, subscription_id: "sub_123" });

    expect(await screen.findByText("Receipt printed")).toBeDefined();
    expect(verifyPayment).toHaveBeenCalledTimes(1);
  });

  it("shows the failure state when the payment did not complete", async () => {
    verifyPayment.mockResolvedValue({ payment_completed: false });
    render(
      <StrictMode>
        <PaymentSuccessPage />
      </StrictMode>,
    );

    expect(await screen.findByText("Payment not completed")).toBeDefined();
  });

  it("counts a payment that never confirmed", async () => {
    // This is the moment a paying customer finds out whether their money did
    // anything, and until now the only trace of it going wrong was a console
    // line. Nothing server-side sees it either: a webhook that never lands
    // produces no event at all.
    verifyPayment.mockResolvedValue({ payment_completed: false });
    render(
      <StrictMode>
        <PaymentSuccessPage />
      </StrictMode>,
    );

    await screen.findByText("Payment not completed");

    const failures = vi
      .mocked(trackEvent)
      .mock.calls.filter(([event]) => event === "subscription:failed");
    expect(failures).toHaveLength(1);
    expect(failures[0][1]).toEqual({
      source: "payment_success_page",
      reason: "confirmation_timeout",
    });
  });

  it("counts a verification that could not complete at all", async () => {
    verifyPayment.mockRejectedValue(new Error("Network Error"));
    render(<PaymentSuccessPage />);

    await screen.findByText("Payment not completed");

    expect(trackEvent).toHaveBeenCalledWith("subscription:failed", {
      source: "payment_success_page",
      reason: "verification_error",
    });
  });

  it("counts nothing when the payment confirmed", async () => {
    render(<PaymentSuccessPage />);

    await screen.findByText("Receipt printed");

    expect(trackEvent).not.toHaveBeenCalledWith(
      "subscription:failed",
      expect.anything(),
    );
  });

  it("sends a user with unfinished onboarding back into the flow", async () => {
    onboarding = { completed: false };
    render(<PaymentSuccessPage />);

    const cta = await screen.findByRole("button", {
      name: /continue to chat/i,
    });
    cta.click();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/onboarding"));
  });

  it("sends an unfinished user back to the wizard to retry, not to pricing", async () => {
    onboarding = { completed: false };
    verifyPayment.mockResolvedValue({ payment_completed: false });
    render(<PaymentSuccessPage />);

    const retry = await screen.findByRole("button", { name: /try again/i });
    retry.click();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/onboarding"));
    expect(createSubscriptionAndRedirect).not.toHaveBeenCalled();
  });

  it("sends a finished user to chat", async () => {
    render(<PaymentSuccessPage />);

    const cta = await screen.findByRole("button", {
      name: /continue to chat/i,
    });
    cta.click();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/c"));
  });
});
