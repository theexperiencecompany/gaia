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
  /**
   * Optional context-specific pitch shown above the plan cards (e.g. a
   * staged-work quota pitch from a 402 response). `null` renders the
   * modal's default copy.
   */
  pitch: string | null;
  offer: PricingOffer | null;
  /**
   * `pitch` swaps the modal's subheading; `offer` re-prices the cards and
   * carries a discount code to checkout. They are independent — a caller may
   * pass either, both, or neither. Taking one object rather than a positional
   * union is deliberate: a bare `openModal` handed straight to an `onPress`
   * receives the press event as its argument, and a positional union would
   * read that event as an offer.
   */
  openModal: (context?: {
    pitch?: string | null;
    offer?: PricingOffer | null;
  }) => void;
  closeModal: () => void;
}

export const usePricingModalStore = create<PricingModalStore>()(
  devtools(
    (set) => ({
      open: false,
      pitch: null,
      offer: null,
      openModal: (context) =>
        set(
          {
            open: true,
            pitch: context?.pitch ?? null,
            offer: context?.offer ?? null,
          },
          false,
          "openModal",
        ),
      closeModal: () =>
        set({ open: false, pitch: null, offer: null }, false, "closeModal"),
    }),
    { name: "pricingModal-store" },
  ),
);
