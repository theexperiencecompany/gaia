import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface PricingModalStore {
  open: boolean;
  /** Discount code the modal was opened with; pre-applied at checkout. */
  discountCode: string | null;
  openModal: (options?: { discountCode?: string }) => void;
  closeModal: () => void;
}

export const usePricingModalStore = create<PricingModalStore>()(
  devtools(
    (set) => ({
      open: false,
      discountCode: null,
      openModal: (options) =>
        set(
          { open: true, discountCode: options?.discountCode ?? null },
          false,
          "openModal",
        ),
      closeModal: () =>
        set({ open: false, discountCode: null }, false, "closeModal"),
    }),
    { name: "pricingModal-store" },
  ),
);
