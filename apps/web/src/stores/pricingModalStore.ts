import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface PricingModalStore {
  open: boolean;
  openModal: () => void;
  closeModal: () => void;
}

export const usePricingModalStore = create<PricingModalStore>()(
  devtools(
    (set) => ({
      open: false,
      openModal: () => set({ open: true }, false, "openModal"),
      closeModal: () => set({ open: false }, false, "closeModal"),
    }),
    { name: "pricingModal-store" },
  ),
);
