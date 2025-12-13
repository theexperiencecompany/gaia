import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface LoginModalStore {
  open: boolean;
  setOpen: (open: boolean) => void;
  openModal: () => void;
  closeModal: () => void;
}

export const useLoginModalStore = create<LoginModalStore>()(
  devtools(
    (set) => ({
      open: false,
      setOpen: (open) => set({ open }, false, "setOpen"),
      openModal: () => set({ open: true }, false, "openModal"),
      closeModal: () => set({ open: false }, false, "closeModal"),
    }),
    { name: "loginModal-store" },
  ),
);

// Selectors
export const useLoginModalOpen = () =>
  useLoginModalStore((state) => state.open);
