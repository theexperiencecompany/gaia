import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const createCheckoutSession = vi.fn();
const getSubscriptionStatus = vi.fn();
const verifyPayment = vi.fn();
const openDodoOverlay = vi.fn();
const closeDodoOverlay = vi.fn();

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: {
    createCheckoutSession: (...args: unknown[]) =>
      createCheckoutSession(...args),
    getSubscriptionStatus: () => getSubscriptionStatus(),
    verifyPayment: (...args: unknown[]) => verifyPayment(...args),
  },
}));

vi.mock("@/features/pricing/lib/dodoOverlay", () => ({
  openDodoOverlay: (...args: unknown[]) => openDodoOverlay(...args),
  closeDodoOverlay: () => closeDodoOverlay(),
}));

import {
  isCheckoutSettled,
  useCheckoutOverlayStore,
} from "@/features/pricing/stores/checkoutOverlayStore";

const SESSION = {
  subscription_id: "sess_1",
  payment_link: "https://checkout.dodopayments.test/sess_1",
  status: "payment_link_created",
};

const FREE = { plan_type: "free" as const, is_subscribed: false };
const PRO = { plan_type: "pro" as const, is_subscribed: true };

/** Runs the pending timers the polling loop schedules, letting each awaited
 *  status read settle in between. */
async function advancePolls(count: number) {
  for (let i = 0; i < count; i++) {
    await vi.advanceTimersByTimeAsync(10_000);
  }
}

describe("checkout overlay state machine", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useCheckoutOverlayStore.getState().reset();
    createCheckoutSession.mockResolvedValue(SESSION);
    openDodoOverlay.mockResolvedValue(undefined);
    getSubscriptionStatus.mockResolvedValue(FREE);
    verifyPayment.mockResolvedValue({ payment_completed: false });
  });

  afterEach(() => {
    useCheckoutOverlayStore.getState().reset();
    vi.useRealTimers();
  });

  it("mints a session for the requested cycle and opens the overlay", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("yearly", "pricing_card");

    // The source rides on the request because the server is now the only
    // emitter of payment:checkout_started — the client fires nothing.
    expect(createCheckoutSession).toHaveBeenCalledWith({
      billing_cycle: "yearly",
      source: "pricing_card",
    });
    expect(openDodoOverlay).toHaveBeenCalledWith(
      SESSION.payment_link,
      expect.any(Function),
    );
    expect(useCheckoutOverlayStore.getState().phase).toBe("open");
  });

  it("confirms against the server, not the overlay's own close event", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "paywall_modal");
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.pay_button_clicked" });
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.closed" });

    // A closed overlay proves nothing on its own — the phase must not jump
    // to confirmed before the webhook has landed.
    expect(useCheckoutOverlayStore.getState().phase).toBe("confirming");

    getSubscriptionStatus.mockResolvedValue(PRO);
    await advancePolls(2);

    expect(useCheckoutOverlayStore.getState().phase).toBe("confirmed");
    expect(closeDodoOverlay).toHaveBeenCalled();
  });

  it("treats a redirect the same as a close — it is not proof of payment", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "paywall_modal");
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.redirect" });

    expect(useCheckoutOverlayStore.getState().phase).toBe("confirming");
  });

  it("admits the delay past the visible budget but keeps polling", async () => {
    // The long wait belongs to the redirect path: Dodo already took the
    // browser away and back, so the charge exists and only the webhook is
    // outstanding. The overlay's own dismissal gets the short grace below.
    useCheckoutOverlayStore.getState().confirmReturnedCheckout("sub_1");

    await vi.advanceTimersByTimeAsync(61_000);
    expect(useCheckoutOverlayStore.getState().phase).toBe("timeout");

    const pollsSoFar = verifyPayment.mock.calls.length;
    verifyPayment.mockResolvedValue({ payment_completed: true });
    await advancePolls(2);

    expect(verifyPayment.mock.calls.length).toBeGreaterThan(pollsSoFar);
    expect(useCheckoutOverlayStore.getState().phase).toBe("confirmed");
  });

  it("stops after the total budget and says the payment is unconfirmed", async () => {
    useCheckoutOverlayStore.getState().confirmReturnedCheckout("sub_1");

    await vi.advanceTimersByTimeAsync(5 * 60_000 + 10_000);
    expect(useCheckoutOverlayStore.getState().phase).toBe("unconfirmed");

    const pollsSoFar = verifyPayment.mock.calls.length;
    await advancePolls(3);
    expect(verifyPayment.mock.calls.length).toBe(pollsSoFar);
  });

  it("hands the plans back seconds after the user closes the sheet, not minutes", async () => {
    // Pressing pay is not evidence of paying: a completed checkout navigates
    // the page to Dodo's return URL, so a closed overlay is the user backing
    // out of a sheet that never went through. Waiting five minutes on that
    // leaves them staring at "Confirming your payment…" with no way out.
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "paywall_modal");
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.pay_button_clicked" });
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.closed" });

    await vi.advanceTimersByTimeAsync(20_000);

    expect(useCheckoutOverlayStore.getState().phase).toBe("unconfirmed");
    expect(isCheckoutSettled(useCheckoutOverlayStore.getState().phase)).toBe(
      true,
    );
  });

  it("still confirms a charge that lands inside the dismissal grace", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "paywall_modal");
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.pay_button_clicked" });
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.closed" });

    getSubscriptionStatus.mockResolvedValue(PRO);
    await advancePolls(1);

    expect(useCheckoutOverlayStore.getState().phase).toBe("confirmed");
  });

  it("settles a returned checkout through verify, with the subscription off the URL", async () => {
    useCheckoutOverlayStore.getState().confirmReturnedCheckout("sub_1");
    expect(useCheckoutOverlayStore.getState().phase).toBe("confirming");

    verifyPayment.mockResolvedValue({ payment_completed: true });
    await advancePolls(2);

    expect(verifyPayment).toHaveBeenCalledWith("sub_1");
    expect(getSubscriptionStatus).not.toHaveBeenCalled();
    expect(useCheckoutOverlayStore.getState().phase).toBe("confirmed");
  });

  it("keeps polling through a failed status read", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "paywall_modal");
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.pay_button_clicked" });
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.closed" });

    getSubscriptionStatus.mockRejectedValueOnce(new Error("network"));
    getSubscriptionStatus.mockResolvedValue(PRO);
    await advancePolls(3);

    expect(useCheckoutOverlayStore.getState().phase).toBe("confirmed");
  });

  it("surfaces an expired link instead of silently sitting open", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "paywall_modal");
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.link_expired" });

    const { phase, error } = useCheckoutOverlayStore.getState();
    expect(phase).toBe("idle");
    expect(error).toMatch(/expired/i);
  });

  it("fails loud when the session comes back with no URL", async () => {
    createCheckoutSession.mockResolvedValue({ ...SESSION, payment_link: null });

    await expect(
      useCheckoutOverlayStore
        .getState()
        .startCheckout("monthly", "paywall_modal"),
    ).rejects.toThrow();
    expect(openDodoOverlay).not.toHaveBeenCalled();
    expect(useCheckoutOverlayStore.getState().phase).toBe("idle");
    expect(useCheckoutOverlayStore.getState().error).toBeTruthy();
  });

  it("stops a stale confirmation loop when a new checkout starts", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "paywall_modal");
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.pay_button_clicked" });
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.closed" });

    await useCheckoutOverlayStore
      .getState()
      .startCheckout("yearly", "pricing_card");
    getSubscriptionStatus.mockResolvedValue(PRO);
    await advancePolls(2);

    // The abandoned loop must not resolve over the newly-opened overlay.
    expect(useCheckoutOverlayStore.getState().phase).toBe("open");
  });
});
