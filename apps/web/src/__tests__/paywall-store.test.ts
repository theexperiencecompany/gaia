import { beforeEach, describe, expect, it } from "vitest";

import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("paywallModalStore", () => {
  beforeEach(() => {
    usePaywallModalStore.setState({
      open: false,
      offer: null,
      dismissible: false,
    });
  });

  it("starts closed with no offer", () => {
    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(false);
    expect(state.offer).toBeNull();
    expect(state.dismissible).toBe(false);
  });

  it("opens with no offer when called with none (composer/toggle call sites)", () => {
    usePaywallModalStore.getState().openModal();

    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.offer).toBeNull();
  });

  it("defaults to non-dismissible when no options are passed (every enforcement call site)", () => {
    usePaywallModalStore.getState().openModal();

    expect(usePaywallModalStore.getState().dismissible).toBe(false);
  });

  it("defaults to non-dismissible even when an offer is passed without options (402 interceptor)", () => {
    usePaywallModalStore.getState().openModal({
      checkoutUrl: "https://checkout.example/session",
      discountCode: null,
    });

    expect(usePaywallModalStore.getState().dismissible).toBe(false);
  });

  it("opens dismissible when explicitly requested (voluntary upgrade entry points)", () => {
    usePaywallModalStore.getState().openModal(undefined, { dismissible: true });

    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.dismissible).toBe(true);
  });

  it("resets dismissible back to false on close", () => {
    usePaywallModalStore.getState().openModal(undefined, { dismissible: true });
    usePaywallModalStore.getState().closeModal();

    expect(usePaywallModalStore.getState().dismissible).toBe(false);
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
