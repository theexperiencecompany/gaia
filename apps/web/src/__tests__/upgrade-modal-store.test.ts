import { beforeEach, describe, expect, it } from "vitest";

import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

describe("upgradeModalStore", () => {
  beforeEach(() => {
    useUpgradeModalStore.setState({
      open: false,
      offer: null,
      dismissible: false,
      source: null,
    });
  });

  it("starts closed with no offer", () => {
    const state = useUpgradeModalStore.getState();
    expect(state.open).toBe(false);
    expect(state.offer).toBeNull();
    expect(state.dismissible).toBe(false);
  });

  it("opens with no offer when called with none (composer/toggle call sites)", () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });

    const state = useUpgradeModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.offer).toBeNull();
  });

  it("defaults to non-dismissible when no options are passed (every enforcement call site)", () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "composer_submit" });

    expect(useUpgradeModalStore.getState().dismissible).toBe(false);
  });

  it("defaults to non-dismissible even when an offer is passed without options (402 interceptor)", () => {
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });

    expect(useUpgradeModalStore.getState().dismissible).toBe(false);
  });

  it("opens dismissible when explicitly requested (voluntary upgrade entry points)", () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { dismissible: true, source: "sidebar" });

    const state = useUpgradeModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.dismissible).toBe(true);
  });

  it("resets dismissible back to false on close", () => {
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { dismissible: true, source: "sidebar" });
    useUpgradeModalStore.getState().closeModal();

    expect(useUpgradeModalStore.getState().dismissible).toBe(false);
  });

  it("carries the 402 payload through openModal", () => {
    useUpgradeModalStore
      .getState()
      .openModal(
        { discountCode: "LAUNCH20", message: "Subscribe to keep chatting" },
        { source: "api_402" },
      );

    const state = useUpgradeModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.offer).toEqual({
      discountCode: "LAUNCH20",
      message: "Subscribe to keep chatting",
    });
  });

  it("clears open and offer on close", () => {
    useUpgradeModalStore
      .getState()
      .openModal(
        { discountCode: "X" },
        { dismissible: true, source: "sidebar" },
      );

    useUpgradeModalStore.getState().closeModal();

    const state = useUpgradeModalStore.getState();
    expect(state.open).toBe(false);
    expect(state.offer).toBeNull();
  });

  it("refuses to close an enforcement-mode modal", () => {
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });

    useUpgradeModalStore.getState().closeModal();

    expect(useUpgradeModalStore.getState().open).toBe(true);
  });

  it("closes an enforcement-mode modal when forced (paid flip, popup mirror)", () => {
    useUpgradeModalStore
      .getState()
      .openModal({ discountCode: null }, { source: "api_402" });

    useUpgradeModalStore.getState().closeModal({ force: true });

    const state = useUpgradeModalStore.getState();
    expect(state.open).toBe(false);
    expect(state.offer).toBeNull();
  });

  it("carries the surface that raised the wall, and drops it on close", () => {
    // "The wall was shown 4,000 times" is not actionable; which surface
    // produced them is. Nothing else records where an open came from.
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { source: "workflow_activation" });

    expect(useUpgradeModalStore.getState().source).toBe("workflow_activation");

    useUpgradeModalStore.getState().closeModal({ force: true });

    expect(useUpgradeModalStore.getState().source).toBeNull();
  });

  it("leaves an already-open wall untouched when more 402s arrive", () => {
    // One user, one wall: a single blocked screen fires a 402 per gated
    // request, and every one of them used to rewrite this store.
    useUpgradeModalStore
      .getState()
      .openModal({ message: "the first wall" }, { source: "api_402" });

    useUpgradeModalStore
      .getState()
      .openModal({ message: "a later 402" }, { source: "api_402" });

    expect(useUpgradeModalStore.getState().offer).toEqual({
      message: "the first wall",
    });
  });

  it("never turns a voluntarily opened modal into a wall", () => {
    // Someone browsing plans from the rate-limit toast must not be trapped
    // behind an undismissable wall by a background request they never made.
    useUpgradeModalStore
      .getState()
      .openModal(undefined, { dismissible: true, source: "sidebar" });

    useUpgradeModalStore
      .getState()
      .openModal({ message: "a background 402" }, { source: "api_402" });

    const state = useUpgradeModalStore.getState();
    expect(state.dismissible).toBe(true);
    useUpgradeModalStore.getState().closeModal();
    expect(useUpgradeModalStore.getState().open).toBe(false);
  });
});
