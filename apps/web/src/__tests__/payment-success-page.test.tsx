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

vi.mock("@/features/auth/hooks/useUser", () => ({
  useUser: () => ({ onboarding }),
}));

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({
    verifyPayment: unstableVerifyIdentity
      ? (...args: unknown[]) => verifyPayment(...args)
      : verifyPayment,
  }),
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

import PaymentSuccessPage from "@/app/[locale]/(landing)/payment/success/page";

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

    expect(await screen.findByText("Welcome to GAIA Pro!")).toBeDefined();
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

    expect(await screen.findByText("Welcome to GAIA Pro!")).toBeDefined();
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

  it("sends a user with unfinished onboarding back into the flow", async () => {
    onboarding = { completed: false };
    render(<PaymentSuccessPage />);

    const cta = await screen.findByRole("button", {
      name: /finish setting up/i,
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
