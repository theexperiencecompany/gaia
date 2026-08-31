import { beforeEach, describe, expect, it } from "vitest";

import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("paywallModalStore", () => {
  beforeEach(() => {
    usePaywallModalStore.setState({ open: false, offer: null });
  });

  it("starts closed with no offer", () => {
    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(false);
    expect(state.offer).toBeNull();
  });

  it("opens with no offer when called with none (composer/toggle call sites)", () => {
    usePaywallModalStore.getState().openModal();

    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.offer).toBeNull();
  });

  it("carries the 402 payload through openModal", () => {
    usePaywallModalStore.getState().openModal({
      checkoutUrl: "https://checkout.example/session",
      discountCode: "LAUNCH20",
      message: "Subscribe to keep chatting",
    });

    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.offer).toEqual({
      checkoutUrl: "https://checkout.example/session",
      discountCode: "LAUNCH20",
      message: "Subscribe to keep chatting",
    });
  });

  it("clears open and offer on close", () => {
    usePaywallModalStore
      .getState()
      .openModal({ checkoutUrl: null, discountCode: "X" });

    usePaywallModalStore.getState().closeModal();

    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(false);
    expect(state.offer).toBeNull();
  });
});
