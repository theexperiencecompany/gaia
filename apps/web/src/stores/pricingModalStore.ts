import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface PricingModalStore {
  open: boolean;
  /**
   * Optional context-specific pitch shown above the plan cards (e.g. a
   * staged-work quota pitch from a 402 response). `null` renders the
   * modal's default copy.
   */
  pitch: string | null;
  openModal: (pitch?: string) => void;
  closeModal: () => void;
}

export const usePricingModalStore = create<PricingModalStore>()(
  devtools(
    (set) => ({
      open: false,
      pitch: null,
      openModal: (pitch) =>
        set({ open: true, pitch: pitch ?? null }, false, "openModal"),
      closeModal: () => set({ open: false, pitch: null }, false, "closeModal"),
    }),
    { name: "pricingModal-store" },
  ),
);
