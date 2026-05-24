import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface IntegrationModalStore {
  isOpen: boolean;
  openModal: () => void;
  closeModal: () => void;
}

export const useIntegrationModalStore = create<IntegrationModalStore>()(
  devtools(
    (set) => ({
      isOpen: false,
      openModal: () => set({ isOpen: true }, false, "openModal"),
      closeModal: () => set({ isOpen: false }, false, "closeModal"),
    }),
    { name: "integrationModal-store" },
  ),
);
