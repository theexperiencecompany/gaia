import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface HoloCardModalStore {
  open: boolean;
  setOpen: (open: boolean) => void;
  openModal: () => void;
  closeModal: () => void;
}

export const useHoloCardModalStore = create<HoloCardModalStore>()(
  devtools(
    (set) => ({
      open: false,
      setOpen: (open) => set({ open }, false, "setOpen"),
      openModal: () => set({ open: true }, false, "openModal"),
      closeModal: () => set({ open: false }, false, "closeModal"),
    }),
    { name: "holoCardModal-store" },
  ),
);

export const useHoloCardModalOpen = () =>
  useHoloCardModalStore((state) => state.open);
