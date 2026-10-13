import { create } from "zustand";
import { devtools } from "zustand/middleware";

/**
 * An offer the modal was opened with — the founder's letter, for one. The code
 * rides along to the Dodo checkout session so it is already applied when the
 * page loads, and the percentage lets the cards show what the reader will
 * actually pay.
 */
export interface PricingOffer {
  discountCode: string;
  discountPercent: number;
}

interface PricingModalStore {
  open: boolean;
  offer: PricingOffer | null;
  openModal: (offer?: PricingOffer) => void;
  closeModal: () => void;
}

export const usePricingModalStore = create<PricingModalStore>()(
  devtools(
    (set) => ({
      open: false,
      offer: null,
      openModal: (offer) =>
        set({ open: true, offer: offer ?? null }, false, "openModal"),
      closeModal: () => set({ open: false, offer: null }, false, "closeModal"),
    }),
    { name: "pricingModal-store" },
  ),
);
