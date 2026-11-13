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

const track = vi.fn();
vi.mock("@/lib/analytics", () => ({
  track: (...args: unknown[]) => track(...args),
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
    // Pressing pay isn't proof of paying: a completed checkout navigates to
    // Dodo's return URL, so a closed overlay means the user backed out —
    // waiting minutes on that would leave "Confirming your payment…" stuck.
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
    useCheckoutOverlayStore
      .getState()
      .handleCheckoutEvent({ event_type: "checkout.opened" });
    getSubscriptionStatus.mockResolvedValue(PRO);
    await advancePolls(2);

    // The abandoned loop must not resolve over the newly-opened overlay.
    expect(useCheckoutOverlayStore.getState().phase).toBe("open");
  });
});

/** The payloads Dodo's overlay posts, as captured from test mode. */
const dodoEvent = (event_type: string, message: Record<string, unknown> = {}) =>
  ({ event_type, data: { message } }) as Parameters<
    ReturnType<typeof useCheckoutOverlayStore.getState>["handleCheckoutEvent"]
  >[0];

describe("checkout overlay under manual redirect", () => {
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

  const handle = (event: ReturnType<typeof dodoEvent>) =>
    useCheckoutOverlayStore.getState().handleCheckoutEvent(event);

  it("hands a declined charge back as a retryable error, in place", async () => {
    // Under manualRedirect Dodo leaves the sheet on "Processing…" and only
    // reports the outcome: without handling it the user is stuck there.
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "onboarding");
    handle(dodoEvent("checkout.opened"));
    handle(dodoEvent("checkout.pay_button_clicked", { payment_id: "x" }));
    handle(dodoEvent("checkout.status", { status: "failed" }));

    const { phase, error } = useCheckoutOverlayStore.getState();
    expect(phase).toBe("idle");
    expect(isCheckoutSettled(phase)).toBe(true);
    expect(error).toMatch(/didn't go through/);
    expect(closeDodoOverlay).toHaveBeenCalled();
    // A decline is the server's payment:failed, not an abandonment.
    handle(dodoEvent("checkout.closed"));
    expect(track).not.toHaveBeenCalled();
  });

  it("settles a succeeded charge with the server, without waiting on a webhook", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("yearly", "onboarding");
    handle(dodoEvent("checkout.opened"));
    handle(dodoEvent("checkout.status", { status: "succeeded" }));
    expect(useCheckoutOverlayStore.getState().phase).toBe("confirming");

    verifyPayment.mockResolvedValue({ payment_completed: true });
    await advancePolls(1);

    // No id: the server resolves the user's checkout sessions against Dodo.
    expect(verifyPayment).toHaveBeenCalledWith(undefined);
    expect(useCheckoutOverlayStore.getState().phase).toBe("confirmed");
  });

  it("never sends the tab back into the app on Dodo's redirect request", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", {
      location: { origin: "https://heygaia.io", assign },
    });
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "onboarding");

    handle(
      dodoEvent("checkout.redirect_requested", {
        redirect_to:
          "https://heygaia.io/onboarding?checkout=returned&email=a%40b.c",
      }),
    );
    expect(assign).not.toHaveBeenCalled();

    // A bank's 3-D Secure page is somewhere the user must actually go.
    handle(
      dodoEvent("checkout.redirect_requested", {
        redirect_to: "https://3ds.bank.example/challenge",
      }),
    );
    expect(assign).toHaveBeenCalledWith(
      new URL("https://3ds.bank.example/challenge"),
    );
    vi.unstubAllGlobals();
  });

  it("records how far a closed checkout got, with its plan and source", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("yearly", "onboarding");
    handle(dodoEvent("checkout.opened"));
    handle(dodoEvent("checkout.customer_details_submitted"));
    handle(dodoEvent("checkout.payment_page_opened"));
    handle(dodoEvent("checkout.closed"));

    expect(track).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith("payment:checkout_abandoned", {
      source: "onboarding",
      billing_cycle: "yearly",
      furthest_step: "payment_page",
    });
    expect(useCheckoutOverlayStore.getState().phase).toBe("idle");
  });

  it("takes down an overlay that never rendered instead of leaving the page frozen", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "pricing_card");

    await vi.advanceTimersByTimeAsync(21_000);

    const { phase, error } = useCheckoutOverlayStore.getState();
    expect(phase).toBe("idle");
    expect(error).toMatch(/didn't load/);
    expect(closeDodoOverlay).toHaveBeenCalled();
    expect(track).toHaveBeenCalledWith("payment:checkout_abandoned", {
      source: "pricing_card",
      billing_cycle: "monthly",
      furthest_step: "not_loaded",
    });
  });

  it("leaves a rendered overlay alone past the load timeout", async () => {
    await useCheckoutOverlayStore
      .getState()
      .startCheckout("monthly", "pricing_card");
    handle(dodoEvent("checkout.opened"));

    await vi.advanceTimersByTimeAsync(21_000);

    expect(useCheckoutOverlayStore.getState().phase).toBe("open");
    expect(closeDodoOverlay).not.toHaveBeenCalled();
  });
});
