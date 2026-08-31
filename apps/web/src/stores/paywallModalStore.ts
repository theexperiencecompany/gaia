import { create } from "zustand";
import { devtools } from "zustand/middleware";

/**
 * Payload carried into the paywall — from a 402 `subscription_required`
 * response, or any other call site that wants to gate an action behind Pro.
 * checkoutUrl/discountCode ride along from the backend so the modal doesn't
 * have to re-derive them; both are optional because non-402 call sites (the
 * composer pre-check, workflow toggle) open the modal with no offer at all.
 */
export interface PaywallOffer {
  checkoutUrl: string | null;
  discountCode: string | null;
  message?: string;
}

interface PaywallModalStore {
  open: boolean;
  offer: PaywallOffer | null;
  openModal: (offer?: PaywallOffer) => void;
  closeModal: () => void;
}

/**
 * The paid-only paywall. Unlike `pricingModalStore` (the optional "Level Up"
 * upsell), this modal is non-dismissible — no backdrop click, no Escape, no
 * close button. `closeModal` exists only for programmatic resets (e.g. once
 * checkout succeeds and `useIsPaid` flips true), never for a user-facing
 * dismiss control.
 */
export const usePaywallModalStore = create<PaywallModalStore>()(
  devtools(
    (set) => ({
      open: false,
      offer: null,
      openModal: (offer) =>
        set({ open: true, offer: offer ?? null }, false, "openModal"),
      closeModal: () => set({ open: false, offer: null }, false, "closeModal"),
    }),
    { name: "paywallModal-store" },
  ),
);
